"""Idempotent AnalysisResult intake and authoritative Risk reconciliation."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from iprisk_contracts import (
    AnalysisCoverage,
    AnalysisResult,
    AnalysisStatus,
    AnalysisType,
    LicenseCandidate,
    LicensePolicyOutcome,
    PatentCandidate,
    ReviewPriority,
)

from ip_risk_agent.application.analysis_jobs.models import (
    AnalysisJob,
    AnalysisJobStatus,
    AnalysisOutcome,
    ProviderFailureSummary,
)
from ip_risk_agent.application.analysis_jobs.transitions import complete_analysis_job
from ip_risk_agent.application.process_change.models import ChangeEvent, ChangeEventStatus
from ip_risk_agent.application.process_change.transitions import (
    complete_change_event,
    fail_change_event,
)
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.audit import AuditEvent, AuditEventType
from ip_risk_agent.core.artifacts import ArtifactState
from ip_risk_agent.core.common import ActorType, DomainInvariantError, normalize_utc, stable_key
from ip_risk_agent.core.notifications import (
    Notification,
    NotificationStatus,
    NotificationType,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskEvidence,
    RiskLifecycleState,
    analysis_is_authoritative,
    decide_lifecycle,
    license_risk_key,
    patent_risk_key,
    risk_evidence_id_for,
    risk_event_id_for,
    risk_id_for,
)

from .retention import (
    EvidenceRetentionPolicy,
    sanitize_excerpt,
    sanitize_failure_message,
    sanitize_metadata,
    sanitize_reference,
    sanitize_summary,
)

Clock = Callable[[], datetime]


class AnalysisResultDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"


class AnalysisResultIntakeError(DomainInvariantError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisResultAcceptance:
    disposition: AnalysisResultDisposition
    analysis_job_id: str
    result_fingerprint: str
    job_status: AnalysisJobStatus
    affected_risk_ids: tuple[str, ...] = ()
    resolved_risk_ids: tuple[str, ...] = ()
    evidence_count: int = 0


@dataclass(frozen=True, slots=True)
class _CandidateProjection:
    risk_key: str
    priority: ReviewPriority
    summary: str
    evidence_ids: tuple[str, ...]


class AnalysisResultIntakeService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
        retention_policy: EvidenceRetentionPolicy | None = None,
        concurrency_attempts: int = 3,
    ) -> None:
        if concurrency_attempts < 1:
            raise ValueError("concurrency_attempts must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._retention = retention_policy or EvidenceRetentionPolicy()
        self._concurrency_attempts = concurrency_attempts

    async def accept_analysis_result(
        self, result: AnalysisResult
    ) -> AnalysisResultAcceptance:
        fingerprint = _result_fingerprint(result)
        last_conflict: ConcurrencyConflictError | None = None
        for _ in range(self._concurrency_attempts):
            try:
                return await self._accept_once(result, fingerprint)
            except ConcurrencyConflictError as exc:
                last_conflict = exc
        assert last_conflict is not None
        raise last_conflict

    async def _accept_once(
        self,
        result: AnalysisResult,
        fingerprint: str,
    ) -> AnalysisResultAcceptance:
        async with self._unit_of_work_factory() as uow:
            job, event, artifact_state, workspace_owner = await _load_context(
                uow, result.analysis_job_id
            )
            _validate_result(job, event, artifact_state, result)
            existing_outcome = job.analysis_outcomes.get(result.analysis_type)
            if existing_outcome is not None:
                if existing_outcome.result_fingerprint != fingerprint:
                    raise AnalysisResultIntakeError(
                        "analysis type already has a different canonical result"
                    )
                return AnalysisResultAcceptance(
                    disposition=AnalysisResultDisposition.DUPLICATE,
                    analysis_job_id=job.id,
                    result_fingerprint=fingerprint,
                    job_status=job.status,
                )

            outcome = _outcome_from_result(result, fingerprint, self._retention)
            outcomes = dict(job.analysis_outcomes)
            outcomes[result.analysis_type] = outcome
            job = replace(job, analysis_outcomes=outcomes)
            affected: list[str] = []
            resolved: list[str] = []
            evidence_count = 0
            occurred_at = max(
                normalize_utc(self._clock(), "analysis_result_intake.clock"),
                normalize_utc(result.completed_at, "analysis_result.completed_at"),
                event.updated_at,
                job.started_at or job.created_at,
            )

            if analysis_is_authoritative(result.status, result.coverage):
                affected, resolved, evidence_count = await self._reconcile(
                    uow,
                    result=result,
                    result_fingerprint=fingerprint,
                    risk_workspace_id=event.risk_workspace_id,
                    occurred_at=occurred_at,
                    workspace_owner=workspace_owner,
                )
                revisions = dict(
                    artifact_state.latest_successful_analysis_revision_by_type
                )
                revisions[result.analysis_type] = result.revision
                await uow.artifacts.save_state(
                    replace(
                        artifact_state,
                        latest_successful_analysis_revision_by_type=revisions,
                        updated_at=max(artifact_state.updated_at, occurred_at),
                    )
                )

            if result.status is AnalysisStatus.FAILED or result.provider_failures:
                await _record_analysis_failure(
                    uow,
                    result=result,
                    result_fingerprint=fingerprint,
                    risk_workspace_id=event.risk_workspace_id,
                    owner_user_id=workspace_owner,
                    occurred_at=occurred_at,
                    retention=self._retention,
                )

            event = replace(event, updated_at=max(event.updated_at, occurred_at))
            job, event = _aggregate_job(job, event, occurred_at=occurred_at)
            await uow.analysis_jobs.save(job)
            await uow.change_events.save(event)
            await uow.commit()

        return AnalysisResultAcceptance(
            disposition=AnalysisResultDisposition.ACCEPTED,
            analysis_job_id=job.id,
            result_fingerprint=fingerprint,
            job_status=job.status,
            affected_risk_ids=tuple(sorted(affected)),
            resolved_risk_ids=tuple(sorted(resolved)),
            evidence_count=evidence_count,
        )

    async def _reconcile(
        self,
        uow: ControlUnitOfWork,
        *,
        result: AnalysisResult,
        result_fingerprint: str,
        risk_workspace_id: str,
        occurred_at: datetime,
        workspace_owner: str,
    ) -> tuple[list[str], list[str], int]:
        projections = _candidate_projections(result, self._retention)
        existing_risks = await uow.risks.list_for_artifact(
            result.artifact_id,
            result.analysis_type,
        )
        existing_by_key = {risk.risk_key: risk for risk in existing_risks}
        if len(existing_by_key) != len(existing_risks):
            raise AnalysisResultIntakeError("duplicate canonical risk key in artifact scope")

        evidence_by_id = {evidence.evidence_id: evidence for evidence in result.evidence}
        affected: list[str] = []
        resolved: list[str] = []
        evidence_count = 0
        for risk_key, projection in projections.items():
            risk = existing_by_key.pop(risk_key, None)
            if risk is None:
                risk_time = occurred_at
                conflicting = await uow.risks.get_by_key(risk_key)
                if conflicting is not None:
                    raise AnalysisResultIntakeError(
                        "stable risk key belongs to a different canonical scope"
                    )
                risk = Risk(
                    id=risk_id_for(risk_key),
                    risk_workspace_id=risk_workspace_id,
                    artifact_id=result.artifact_id,
                    analysis_type=result.analysis_type,
                    risk_key=risk_key,
                    lifecycle_state=RiskLifecycleState.NEW,
                    review_disposition=ReviewDisposition.UNREVIEWED,
                    review_priority=projection.priority,
                    summary=projection.summary,
                    first_seen_at=occurred_at,
                    last_seen_at=occurred_at,
                    latest_analysis_job_id=result.analysis_job_id,
                    updated_at=occurred_at,
                    latest_evidence_revision=result.revision,
                )
                previous_state = None
                previous_priority = None
                await uow.risks.add(risk)
            else:
                previous_state = risk.lifecycle_state
                previous_priority = risk.review_priority
                risk_time = max(
                    occurred_at,
                    risk.last_seen_at,
                    risk.updated_at,
                    risk.resolved_at or occurred_at,
                )
                decision = decide_lifecycle(
                    previous_state,
                    candidate_present=True,
                    status=result.status,
                    coverage=result.coverage,
                )
                risk = replace(
                    risk,
                    lifecycle_state=decision.next_state,
                    review_priority=projection.priority,
                    summary=projection.summary,
                    last_seen_at=risk_time,
                    latest_analysis_job_id=result.analysis_job_id,
                    latest_evidence_revision=result.revision,
                    resolved_at=None,
                    updated_at=risk_time,
                )
                await uow.risks.save(risk)

            evidence_refs: list[str] = []
            for evidence_id in projection.evidence_ids:
                source = evidence_by_id[evidence_id]
                evidence = RiskEvidence(
                    id=risk_evidence_id_for(risk.id, result.analysis_job_id, evidence_id),
                    risk_id=risk.id,
                    analysis_job_id=result.analysis_job_id,
                    evidence_id_from_result=evidence_id,
                    evidence_type=source.evidence_type.value,
                    excerpt=sanitize_excerpt(source.excerpt, self._retention),
                    reference=sanitize_reference(source.reference, self._retention),
                    source_revision=result.revision,
                    created_at=risk_time,
                    metadata_safe=sanitize_metadata(source.metadata_safe, self._retention),
                )
                await uow.risks.add_evidence(evidence)
                evidence_refs.append(evidence.id)
                evidence_count += 1

            lifecycle_decision = decide_lifecycle(
                previous_state,
                candidate_present=True,
                status=result.status,
                coverage=result.coverage,
            )
            assert lifecycle_decision.event_type is not None
            await uow.risks.append_event(
                _risk_event(
                    risk=risk,
                    result_fingerprint=result_fingerprint,
                    event_type=lifecycle_decision.event_type,
                    occurred_at=risk_time,
                    analysis_job_id=result.analysis_job_id,
                    previous_state=previous_state,
                    evidence_refs=tuple(evidence_refs),
                )
            )
            if previous_priority is not None and previous_priority is not risk.review_priority:
                await uow.risks.append_event(
                    _priority_event(
                        risk=risk,
                        result_fingerprint=result_fingerprint,
                        previous_priority=previous_priority,
                        occurred_at=risk_time,
                        analysis_job_id=result.analysis_job_id,
                    )
                )
            if (
                lifecycle_decision.event_type is RiskEventType.REOPENED
                or (
                    risk.review_priority is ReviewPriority.HIGH
                    and previous_priority is not ReviewPriority.HIGH
                )
            ):
                notification_type = (
                    NotificationType.RISK_REOPENED
                    if lifecycle_decision.event_type is RiskEventType.REOPENED
                    else NotificationType.RISK_HIGH_DETECTED
                )
                await uow.notifications.add(
                    _risk_notification(
                        risk=risk,
                        owner_user_id=workspace_owner,
                        result_fingerprint=result_fingerprint,
                        notification_type=notification_type,
                        occurred_at=risk_time,
                    )
                )
            affected.append(risk.id)

        for risk in existing_by_key.values():
            decision = decide_lifecycle(
                risk.lifecycle_state,
                candidate_present=False,
                status=result.status,
                coverage=result.coverage,
            )
            if decision.next_state is not RiskLifecycleState.RESOLVED or not decision.changed:
                continue
            risk_time = max(occurred_at, risk.last_seen_at, risk.updated_at)
            updated = replace(
                risk,
                lifecycle_state=RiskLifecycleState.RESOLVED,
                resolved_at=risk_time,
                latest_analysis_job_id=result.analysis_job_id,
                updated_at=risk_time,
            )
            await uow.risks.save(updated)
            await uow.risks.append_event(
                _risk_event(
                    risk=updated,
                    result_fingerprint=result_fingerprint,
                    event_type=RiskEventType.RESOLVED,
                    occurred_at=risk_time,
                    analysis_job_id=result.analysis_job_id,
                    previous_state=risk.lifecycle_state,
                    evidence_refs=(),
                )
            )
            affected.append(updated.id)
            resolved.append(updated.id)
        return affected, resolved, evidence_count


async def _load_context(
    uow: ControlUnitOfWork,
    analysis_job_id: str,
) -> tuple[AnalysisJob, ChangeEvent, ArtifactState, str]:
    job = await uow.analysis_jobs.get(analysis_job_id)
    if job is None:
        raise RecordNotFoundError(f"analysis job was not found: {analysis_job_id!r}")
    event = await uow.change_events.get(job.change_event_id)
    artifact = await uow.artifacts.get(job.artifact_id)
    artifact_state = await uow.artifacts.get_state(job.artifact_id)
    if event is None or artifact is None or artifact_state is None:
        raise RecordNotFoundError("analysis result canonical context is incomplete")
    workspace = await uow.workspaces.get(event.risk_workspace_id)
    if workspace is None:
        raise RecordNotFoundError("analysis result workspace was not found")
    if (
        event.artifact_id != artifact.id
        or event.revision != job.revision
        or artifact.risk_workspace_id != workspace.id
        or job.artifact_id != artifact.id
    ):
        raise AnalysisResultIntakeError("analysis result canonical context is inconsistent")
    return job, event, artifact_state, workspace.owner_user_id


def _validate_result(
    job: AnalysisJob,
    event: ChangeEvent,
    artifact_state: ArtifactState,
    result: AnalysisResult,
) -> None:
    existing = job.analysis_outcomes.get(result.analysis_type)
    if existing is None and (
        job.status is not AnalysisJobStatus.RUNNING
        or event.status is not ChangeEventStatus.PROCESSING
    ):
        raise AnalysisResultIntakeError("new result requires a running canonical job")
    if result.artifact_id != job.artifact_id or result.revision != job.revision:
        raise AnalysisResultIntakeError("result artifact or revision does not match job")
    if result.analysis_type not in job.requested_analysis_types:
        raise AnalysisResultIntakeError("result analysis type was not requested by the job")
    if job.started_at is None or result.started_at < job.started_at:
        raise AnalysisResultIntakeError("result predates the current job attempt")
    if existing is None and artifact_state.latest_revision != result.revision:
        raise AnalysisResultIntakeError("result revision is no longer canonical latest")
    if result.status is AnalysisStatus.SUCCEEDED and result.coverage is AnalysisCoverage.COMPLETE:
        if result.provider_failures:
            raise AnalysisResultIntakeError(
                "complete successful result cannot contain provider failures"
            )
    if result.status is AnalysisStatus.FAILED and not result.provider_failures:
        raise AnalysisResultIntakeError("FAILED result requires provider failure context")


def _outcome_from_result(
    result: AnalysisResult,
    fingerprint: str,
    retention: EvidenceRetentionPolicy,
) -> AnalysisOutcome:
    return AnalysisOutcome(
        analysis_type=result.analysis_type,
        result_fingerprint=fingerprint,
        status=result.status,
        coverage=result.coverage,
        analyzer_version=sanitize_failure_message(
            result.versions.analyzer_version,
            retention,
        ),
        started_at=result.started_at,
        completed_at=result.completed_at,
        provider_failures=tuple(
            ProviderFailureSummary(
                provider=sanitize_failure_message(failure.provider, retention),
                category=sanitize_failure_message(failure.category, retention),
                retryable=failure.retryable,
                safe_message=sanitize_failure_message(
                    failure.safe_message,
                    retention,
                ),
            )
            for failure in result.provider_failures
        ),
        model_id=_safe_optional(result.versions.model_id, retention),
        prompt_version=_safe_optional(result.versions.prompt_version, retention),
        policy_version=_safe_optional(result.versions.policy_version, retention),
        rag_corpus_version=_safe_optional(
            result.versions.rag_corpus_version,
            retention,
        ),
    )


def _aggregate_job(
    job: AnalysisJob,
    event: ChangeEvent,
    *,
    occurred_at: datetime,
) -> tuple[AnalysisJob, ChangeEvent]:
    if set(job.analysis_outcomes) != set(job.requested_analysis_types):
        return job, event
    outcomes = tuple(job.analysis_outcomes.values())
    if any(outcome.status is AnalysisStatus.FAILED for outcome in outcomes):
        failure_safe = "one or more requested analyses failed"
        return (
            complete_analysis_job(
                job,
                status=AnalysisJobStatus.FAILED,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            ),
            fail_change_event(
                event,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            ),
        )
    if all(
        outcome.status is AnalysisStatus.SUCCEEDED
        and outcome.coverage is AnalysisCoverage.COMPLETE
        for outcome in outcomes
    ):
        status = AnalysisJobStatus.SUCCEEDED
        failure_safe = None
    else:
        status = AnalysisJobStatus.INCONCLUSIVE
        failure_safe = "one or more requested analyses were non-authoritative"
    return (
        complete_analysis_job(
            job,
            status=status,
            occurred_at=occurred_at,
            failure_safe=failure_safe,
        ),
        complete_change_event(event, occurred_at=occurred_at),
    )


def _candidate_projections(
    result: AnalysisResult,
    retention: EvidenceRetentionPolicy,
) -> dict[str, _CandidateProjection]:
    projections: dict[str, _CandidateProjection] = {}
    for candidate in result.candidates:
        if isinstance(candidate, PatentCandidate):
            application_number = _normalized_token(
                candidate.normalized_application_number,
                "patent application number",
                remove_separators=True,
            )
            risk_key = patent_risk_key(result.artifact_id, application_number)
            priority = candidate.suggested_review_priority
            summary = sanitize_summary(candidate.title, retention)
        elif isinstance(candidate, LicenseCandidate):
            ecosystem = _normalized_token(candidate.ecosystem, "license ecosystem")
            package_name = _normalized_token(
                candidate.normalized_package_name,
                "license package name",
            )
            version = (
                None
                if candidate.resolved_version is None
                else unicodedata.normalize("NFKC", candidate.resolved_version).strip()
            )
            if version == "":
                raise AnalysisResultIntakeError("resolved license version cannot be empty")
            expression = " ".join(
                unicodedata.normalize(
                    "NFKC", candidate.normalized_license_expression
                ).split()
            ).upper()
            if not expression:
                raise AnalysisResultIntakeError("license expression cannot be empty")
            risk_key = license_risk_key(
                result.artifact_id,
                ecosystem,
                package_name,
                version,
                expression,
            )
            priority = _license_priority(candidate.policy_outcome)
            version_label = version or "unresolved"
            summary = sanitize_summary(
                f"{ecosystem}:{package_name}@{version_label} — {expression}",
                retention,
            )
        else:  # pragma: no cover - frozen contract validation guards this
            raise AnalysisResultIntakeError("unsupported candidate type")
        if risk_key in projections:
            raise AnalysisResultIntakeError("duplicate stable candidate identity")
        projections[risk_key] = _CandidateProjection(
            risk_key=risk_key,
            priority=priority,
            summary=summary,
            evidence_ids=tuple(dict.fromkeys(candidate.evidence_ids)),
        )
    return projections


def _normalized_token(value: str, field_name: str, *, remove_separators: bool = False) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if remove_separators:
        normalized = "".join(
            character
            for character in normalized
            if not character.isspace() and character not in {"-", "_"}
        )
    if not normalized:
        raise AnalysisResultIntakeError(f"{field_name} cannot be empty")
    return normalized


def _license_priority(outcome: LicensePolicyOutcome) -> ReviewPriority:
    return {
        LicensePolicyOutcome.POLICY_CONFLICT: ReviewPriority.HIGH,
        LicensePolicyOutcome.REVIEW_REQUIRED: ReviewPriority.HIGH,
        LicensePolicyOutcome.NOTICE_REQUIRED: ReviewPriority.MEDIUM,
        LicensePolicyOutcome.UNKNOWN: ReviewPriority.MEDIUM,
        LicensePolicyOutcome.NO_ACTION: ReviewPriority.LOW,
    }[outcome]


def _risk_event(
    *,
    risk: Risk,
    result_fingerprint: str,
    event_type: RiskEventType,
    occurred_at: datetime,
    analysis_job_id: str,
    previous_state: RiskLifecycleState | None,
    evidence_refs: tuple[str, ...],
) -> RiskEvent:
    return RiskEvent(
        id=risk_event_id_for(risk.id, result_fingerprint, event_type.value),
        risk_id=risk.id,
        event_type=event_type,
        actor_type=ActorType.SYSTEM,
        occurred_at=occurred_at,
        previous_state_safe={
            "lifecycle_state": None if previous_state is None else previous_state.value,
        },
        new_state_safe={
            "lifecycle_state": risk.lifecycle_state.value,
            "review_priority": risk.review_priority.value,
        },
        analysis_job_id=analysis_job_id,
        evidence_refs=evidence_refs,
    )


def _priority_event(
    *,
    risk: Risk,
    result_fingerprint: str,
    previous_priority: ReviewPriority,
    occurred_at: datetime,
    analysis_job_id: str,
) -> RiskEvent:
    return RiskEvent(
        id=risk_event_id_for(
            risk.id,
            result_fingerprint,
            RiskEventType.PRIORITY_CHANGED.value,
        ),
        risk_id=risk.id,
        event_type=RiskEventType.PRIORITY_CHANGED,
        actor_type=ActorType.SYSTEM,
        occurred_at=occurred_at,
        previous_state_safe={"review_priority": previous_priority.value},
        new_state_safe={"review_priority": risk.review_priority.value},
        analysis_job_id=analysis_job_id,
    )


def _risk_notification(
    *,
    risk: Risk,
    owner_user_id: str,
    result_fingerprint: str,
    notification_type: NotificationType,
    occurred_at: datetime,
) -> Notification:
    return Notification(
        id=stable_key(
            "notification",
            (risk.id, result_fingerprint, notification_type.value),
        ),
        user_id=owner_user_id,
        risk_workspace_id=risk.risk_workspace_id,
        notification_type=notification_type,
        status=NotificationStatus.UNREAD,
        created_at=occurred_at,
        metadata_safe={"risk_id": risk.id, "analysis_type": risk.analysis_type.value},
    )


async def _record_analysis_failure(
    uow: ControlUnitOfWork,
    *,
    result: AnalysisResult,
    result_fingerprint: str,
    risk_workspace_id: str,
    owner_user_id: str,
    occurred_at: datetime,
    retention: EvidenceRetentionPolicy,
) -> None:
    categories = tuple(
        sorted(
            {
                sanitize_failure_message(failure.category, retention)
                for failure in result.provider_failures
            }
        )
    )
    metadata = {
        "analysis_job_id": result.analysis_job_id,
        "analysis_type": result.analysis_type.value,
        "status": result.status.value,
        "coverage": result.coverage.value,
        "provider_failure_categories": categories,
    }
    await uow.audit.append(
        AuditEvent(
            id=stable_key(
                "audit",
                (result.analysis_job_id, result_fingerprint, "analysis-failure"),
            ),
            risk_workspace_id=risk_workspace_id,
            event_type=AuditEventType.ANALYSIS_FAILED,
            actor_type=ActorType.SYSTEM,
            occurred_at=occurred_at,
            metadata_safe=metadata,
        )
    )
    await uow.notifications.add(
        Notification(
            id=stable_key(
                "notification",
                (result.analysis_job_id, result_fingerprint, "analysis-failure"),
            ),
            user_id=owner_user_id,
            risk_workspace_id=risk_workspace_id,
            notification_type=NotificationType.ANALYSIS_FAILED,
            status=NotificationStatus.UNREAD,
            created_at=occurred_at,
            metadata_safe=metadata,
        )
    )


def _result_fingerprint(result: AnalysisResult) -> str:
    payload = json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(payload).hexdigest()}"


def _safe_optional(
    value: str | None,
    retention: EvidenceRetentionPolicy,
) -> str | None:
    return None if value is None else sanitize_failure_message(value, retention)


__all__ = [
    "AnalysisResultAcceptance",
    "AnalysisResultDisposition",
    "AnalysisResultIntakeError",
    "AnalysisResultIntakeService",
]
