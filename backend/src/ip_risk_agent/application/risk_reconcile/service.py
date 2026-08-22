"""Idempotent AnalysisResult intake and authoritative Risk reconciliation."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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
    LifecycleDecision,
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskEvidence,
    RiskLifecycleState,
    analysis_is_authoritative,
    decide_lifecycle,
    should_revive,
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
    """이 예외의 메시지는 모두 개발자가 쓴 상수다.

    그래서 진단 로그에 사유를 노출해도 사용자 데이터나 provider 페이로드가 새지
    않는다. 클래스 이름만 남기면 어떤 불변조건이 깨졌는지 알 수 없어 배포에서
    원인을 좁힐 수 없었다.
    """


class SupersededRevisionError(AnalysisResultIntakeError):
    """이 실행이 맡은 판본보다 새 판본이 소스에 있다.

    결함이 아니다. 소스가 앞서 나갔으니 이 결과를 받아들이면 옛 판본의 내용으로
    현재 상태를 덮게 된다. 새 판본을 맡은 실행이 이미 있으므로 이쪽은 버리는 것이
    맞다.

    파이프라인 시작에서 걸리면 :data:`SOURCE:REVISION_SUPERSEDED` 로 끝나는데,
    분석하는 사이에 판본이 바뀌면 여기까지 와서야 걸린다. 사용자에게는 같은
    일이므로 같은 코드로 끝나야 한다 — 예전에는 이쪽만
    ``CONTRACT:CANONICAL_INTAKE_REJECTED`` 라는 결함 코드로 보였다.
    """


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
    #: 근거 ID -> 그 근거 본문 안에서 강조할 구간. 후보마다 다르다 — 같은 청구항을
    #: 두 후보가 다른 문장으로 인용할 수 있어 근거 원장에 하나만 둘 수 없다.
    quote_spans: Mapping[str, Mapping[str, int]] = field(default_factory=dict)


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
                revived = should_revive(risk.review_disposition)
                if revived:
                    # 추적이 끊겨 제외됐던 파일이 다시 대상이 됐다. 이력을 잇기 위해
                    # 새 Risk 를 만들지 않고 이것을 되살리되, 제외되어 있던 동안의
                    # 판단은 유효하지 않으므로 처음 본 것처럼 되돌린다.
                    decision = LifecycleDecision(
                        previous_state,
                        RiskLifecycleState.NEW,
                        RiskEventType.DETECTED,
                        True,
                    )
                else:
                    decision = decide_lifecycle(
                        previous_state,
                        candidate_present=True,
                        status=result.status,
                        coverage=result.coverage,
                    )
                risk = replace(
                    risk,
                    lifecycle_state=decision.next_state,
                    review_disposition=(
                        ReviewDisposition.UNREVIEWED
                        if revived
                        else risk.review_disposition
                    ),
                    # 처분이 바뀌면 저장소가 review_version 을 하나 올릴 것을 요구한다.
                    review_version=(
                        risk.review_version + 1 if revived else risk.review_version
                    ),
                    review_priority=projection.priority,
                    summary=projection.summary,
                    last_seen_at=risk_time,
                    latest_analysis_job_id=result.analysis_job_id,
                    latest_evidence_revision=result.revision,
                    resolved_at=None,
                    updated_at=risk_time,
                )
                await uow.risks.save(risk)

            # 같은 문서를 다시 검사하면 분석 실행 ID 가 같고, 근거 문서 ID 는
            # 그것에서 결정된다. 실행 결과는 초기화되는데 근거만 남아 있으면 같은
            # ID 를 다시 만들려다 충돌한다. 이번 실행이 앞서 남긴 것을 먼저 걷어
            # 낸다 — 후보가 줄었을 때 지난번 근거가 남는 것도 함께 막는다.
            await uow.risks.clear_evidence(risk.id, result.analysis_job_id)

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
                    metadata_safe=sanitize_metadata(
                        _with_quote_span(
                            source.metadata_safe, projection.quote_spans.get(evidence_id)
                        ),
                        self._retention,
                    ),
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
            # 이력은 덧붙이기만 한다. 그런데 이력 ID 는 결과 지문에서 결정되므로,
            # 바뀐 것이 없는 재검사는 **같은 이력을 다시 쓰려 한다.** 같은 지문은
            # 같은 관측이라는 뜻이므로 이미 있으면 그대로 둔다. 지문이 다르면
            # ID 도 달라 새 이력이 남는다.
            recorded_event_ids = {item.id for item in await uow.risks.list_events(risk.id)}
            await _append_event_once(
                uow,
                recorded_event_ids,
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
                await _append_event_once(
                    uow,
                    recorded_event_ids,
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
                await _add_notification_once(
                    uow,
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
        raise SupersededRevisionError("result revision is no longer canonical latest")
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


#: provider 호출 한도가 소진되면 다른 실패와 다르게 다뤄야 한다. 코드를 고칠 일이
#: 아니라 키를 늘리거나 기다릴 일이고, 그때까지 재시도해도 소용이 없다.
#: 화면이 이 코드를 보고 별도 안내를 띄운다.
PROVIDER_QUOTA_EXHAUSTED = "PROVIDER:QUOTA_EXHAUSTED"

#: Contract 의 ``ProviderFailure.category`` 값이다. Intelligence plane 의 enum 을
#: 여기서 import 하면 계층이 뒤집히므로 계약 값으로 비교한다.
_RATE_LIMITED_CATEGORY = "RATE_LIMITED"


def _failure_reason(outcomes: tuple[AnalysisOutcome, ...]) -> str:
    """실패의 원인이 provider 한도인지 가려낸다.

    한도 소진을 "분석이 실패했습니다" 로 뭉뚱그리면 사용자는 무엇을 해야 할지 알 수
    없다. 코드를 고칠 일이 아니라 키를 늘리거나 초기화를 기다릴 일이다.

    실패한 결과의 provider 오류가 **전부** 한도 초과일 때만 이 코드를 쓴다. 다른
    실패가 섞여 있으면 그쪽이 먼저 볼 문제다.
    """
    failures = [
        failure
        for outcome in outcomes
        if outcome.status is AnalysisStatus.FAILED
        for failure in outcome.provider_failures
    ]
    if failures and all(
        failure.category == _RATE_LIMITED_CATEGORY for failure in failures
    ):
        return PROVIDER_QUOTA_EXHAUSTED
    return "one or more requested analyses failed"


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
        failure_safe = _failure_reason(outcomes)
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
        # 다른 실패와 같은 형태의 코드를 쓴다. 예전에는 영어 한 문장이 그대로
        # 화면에 나와, 미판정을 실패로 읽게 만들었다.
        failure_safe = "ANALYSIS:INCOMPLETE_COVERAGE"
    return (
        complete_analysis_job(
            job,
            status=status,
            occurred_at=occurred_at,
            failure_safe=failure_safe,
        ),
        complete_change_event(event, occurred_at=occurred_at),
    )


def _quote_spans(candidate) -> dict[str, dict[str, int]]:
    """후보 metadata 에 실린 인용 구간을 꺼낸다.

    분석기가 인용의 실재를 확인한 것만 담겨 있다. 여기서는 모양만 검사한다 —
    canonical 은 provider metadata 를 믿지 않는다.
    """
    raw = getattr(candidate, "provider_metadata_safe", None) or {}
    spans = raw.get("quote_spans")
    if not isinstance(spans, Mapping):
        return {}
    checked: dict[str, dict[str, int]] = {}
    for evidence_id, span in spans.items():
        if not isinstance(span, Mapping):
            continue
        start, end = span.get("start"), span.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < 0 or end <= start:
            continue
        checked[str(evidence_id)] = {"start": start, "end": end}
    return checked


def _with_quote_span(
    metadata: Mapping[str, object], span: Mapping[str, int] | None
) -> Mapping[str, object]:
    """근거 metadata 에 강조 구간을 얹는다.

    화면은 저장된 excerpt 를 보여 주고 그 안의 이 구간만 강조한다. 그래서 구간은
    excerpt 기준이어야 하는데, excerpt 는 보존 정책이 잘라낼 수 있다. 잘린 뒤로
    넘어가는 구간은 가리킬 곳이 없으므로 붙이지 않는다.
    """
    if span is None:
        return metadata
    merged = dict(metadata)
    merged["quote_start"] = span["start"]
    merged["quote_end"] = span["end"]
    return merged


def _is_risk_worthy(priority: ReviewPriority) -> bool:
    """이 후보를 Risk 로 다룰지. 상·중만 Risk 다.

    검토 우선도는 "확실히 risk" 에서 "전혀 risk 아님" 까지의 눈금이고, **하 등급은
    그 눈금의 아래쪽 전부**를 뜻한다. 즉 하는 "낮은 위험" 이 아니라 "우리가 관리할
    위험이 아니다" 는 판정이다. 그래서 Risk 를 만들지 않는다.

    이 규칙 하나로 lifecycle 이 자연스럽게 따라온다. 하 등급 후보는 투영에서 빠지고,
    이미 있던 Risk 라면 ``candidate_present=False`` 경로를 타 ``RESOLVED`` 가 된다.
    사용자는 그렇게 닫힌 Risk 를 확인하고 받아들이면 된다.

    주의 — 이것은 "모른다" 와 다르다. 분석이 권위적이지 않으면(``INCONCLUSIVE``,
    ``PARTIAL``) 애초에 이 경로가 Risk 를 바꾸지 못한다. 하 등급은 **알아보고 나서**
    관리 대상이 아니라고 판정한 것이다.
    """
    return priority is not ReviewPriority.LOW


def _candidate_projections(
    result: AnalysisResult,
    retention: EvidenceRetentionPolicy,
) -> dict[str, _CandidateProjection]:
    projections: dict[str, _CandidateProjection] = {}
    # 중복 검사는 하 등급 후보까지 포함해서 한다. 투영에서 빠지는 것과 같은 후보가
    # 두 번 오는 것은 다른 문제다. 후자는 결과가 잘못된 것이므로 넘기면 안 된다.
    seen_keys: set[str] = set()
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
        if risk_key in seen_keys:
            raise AnalysisResultIntakeError("duplicate stable candidate identity")
        seen_keys.add(risk_key)
        if not _is_risk_worthy(priority):
            continue
        projections[risk_key] = _CandidateProjection(
            risk_key=risk_key,
            priority=priority,
            summary=summary,
            evidence_ids=tuple(dict.fromkeys(candidate.evidence_ids)),
            quote_spans=_quote_spans(candidate),
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


async def _append_event_once(uow, recorded_ids: set[str], event: RiskEvent) -> None:
    """같은 이력을 두 번 쓰지 않는다.

    이력 ID 는 (Risk, 결과 지문, 이력 종류) 에서 결정된다. 같은 ID 는 같은 관측을
    뜻하므로 다시 쓸 것이 없다. 바뀐 것이 없는 재검사가 정확히 이 경우다.

    ``recorded_ids`` 를 함께 갱신한다. 한 번의 조정 안에서 이력을 둘 이상 남길 수
    있고, 저장소는 아직 그것을 돌려주지 않는다.
    """
    if event.id in recorded_ids:
        return
    recorded_ids.add(event.id)
    await uow.risks.append_event(event)


async def _add_notification_once(uow, notification: Notification) -> None:
    """알림도 결과 지문에서 ID 가 나온다. 같은 관측을 두 번 알리지 않는다."""
    if await uow.notifications.get(notification.id) is not None:
        return
    await uow.notifications.add(notification)


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
