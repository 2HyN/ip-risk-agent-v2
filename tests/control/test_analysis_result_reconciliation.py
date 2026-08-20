from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts import (
    AnalysisCoverage,
    AnalysisResult,
    AnalysisStatus,
    AnalysisType,
    AnalysisVersions,
    ChangeType,
    Evidence,
    EvidenceType,
    LicenseCandidate,
    LicensePolicyOutcome,
    PatentCandidate,
    ProviderFailure,
    ReviewPriority,
    SourceArtifactRef,
    SourceChange,
    SourceType,
)
from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.process_change import ChangeEvent, ChangeEventStatus
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.application.risk_reconcile import (
    AnalysisResultDisposition,
    AnalysisResultIntakeError,
    AnalysisResultIntakeService,
    EvidenceRetentionPolicy,
)
from ip_risk_agent.application.security_gate import REDACTION_PLACEHOLDER
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.notifications import NotificationType
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    RiskEventType,
    RiskLifecycleState,
    license_risk_key,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


async def seed_artifact_context() -> InMemoryControlStore:
    store = InMemoryControlStore()
    async with store() as uow:
        await uow.workspaces.add(
            RiskWorkspace(
                "vws-1",
                "Workspace",
                "owner-1",
                "security-v1",
                "retention-v1",
                NOW,
                NOW,
            )
        )
        await uow.artifacts.add(
            Artifact(
                "artifact-1",
                "vws-1",
                "mount-1",
                "source-1",
                SourceType.GITHUB,
                "repo:path:src/main.py",
                "main.py",
                "Backend/src/main.py",
                ArtifactStatus.ACTIVE,
                NOW,
                NOW,
            ),
            ArtifactState(
                "artifact-1",
                "revision-0",
                "sha256:revision-0",
                ArtifactAvailability.AVAILABLE,
                NOW,
            ),
        )
        await uow.commit()
    return store


async def add_running_job(
    store: InMemoryControlStore,
    *,
    suffix: str,
    revision: str,
    requested: tuple[AnalysisType, ...] = (AnalysisType.PATENT,),
    offset_seconds: int = 0,
) -> tuple[str, datetime]:
    started_at = NOW + timedelta(seconds=offset_seconds + 1)
    async with store() as uow:
        state = await uow.artifacts.get_state("artifact-1")
        assert state is not None
        await uow.artifacts.save_state(
            replace(
                state,
                latest_revision=revision,
                latest_checksum=f"sha256:{revision}",
                updated_at=max(state.updated_at, NOW + timedelta(seconds=offset_seconds)),
            )
        )
        event = ChangeEvent(
            id=f"change-{suffix}",
            event_fingerprint=f"fingerprint-{suffix}",
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            source_workspace_id="source-1",
            source_artifact_id="repo:path:src/main.py",
            source_type=SourceType.GITHUB,
            change_type=ChangeType.UPDATE,
            revision=revision,
            previous_revision=None,
            observed_at=NOW + timedelta(seconds=offset_seconds),
            status=ChangeEventStatus.PROCESSING,
            attempts=1,
            created_at=NOW + timedelta(seconds=offset_seconds),
            updated_at=started_at,
            source_change=SourceChange(
                contract_version="1",
                event_id=f"provider-event-{suffix}",
                event_fingerprint=f"fingerprint-{suffix}",
                risk_workspace_id="vws-1",
                mount_id="mount-1",
                source_workspace_id="source-1",
                source_type=SourceType.GITHUB,
                artifact=SourceArtifactRef(
                    source_artifact_id="repo:path:src/main.py",
                    display_name="main.py",
                ),
                change_type=ChangeType.UPDATE,
                revision=revision,
                observed_at=NOW + timedelta(seconds=offset_seconds),
                safe_metadata={},
            ),
            artifact_id="artifact-1",
            lease_expires_at=started_at + timedelta(minutes=5),
        )
        job = AnalysisJob(
            id=f"job-{suffix}",
            change_event_id=event.id,
            artifact_id="artifact-1",
            revision=revision,
            requested_analysis_types=requested,
            status=AnalysisJobStatus.RUNNING,
            created_at=NOW + timedelta(seconds=offset_seconds),
            started_at=started_at,
        )
        await uow.change_events.add(event)
        await uow.analysis_jobs.add(job)
        await uow.commit()
    return job.id, started_at


def patent_result(
    job_id: str,
    revision: str,
    started_at: datetime,
    *,
    application_number: str = "KR-10-2026-000001",
    title: str = "Candidate ranking method",
    priority: ReviewPriority = ReviewPriority.HIGH,
    status: AnalysisStatus = AnalysisStatus.SUCCEEDED,
    coverage: AnalysisCoverage = AnalysisCoverage.COMPLETE,
    include_candidate: bool = True,
    provider_failures: list[ProviderFailure] | None = None,
) -> AnalysisResult:
    evidence = Evidence(
        evidence_id="evidence-1",
        evidence_type=EvidenceType.PATENT_CLAIM,
        excerpt="API_KEY=secret-value\nA minimal matching claim excerpt.",
        reference="https://example.invalid/patent/1?token=secret#claim-1",
        metadata_safe={"claim": 1, "access_token": "metadata-secret"},
    )
    candidates = (
        [
            PatentCandidate(
                normalized_application_number=application_number,
                title=title,
                suggested_review_priority=priority,
                matched_elements=["candidate ranking"],
                evidence_ids=[evidence.evidence_id],
                provider_metadata_safe={"jurisdiction": "KR"},
            )
        ]
        if include_candidate
        else []
    )
    return AnalysisResult(
        contract_version="1",
        analysis_job_id=job_id,
        artifact_id="artifact-1",
        revision=revision,
        analysis_type=AnalysisType.PATENT,
        status=status,
        coverage=coverage,
        candidates=candidates,
        evidence=[evidence] if include_candidate else [],
        provider_failures=provider_failures or [],
        versions=AnalysisVersions(
            analyzer_version="patent-v1",
            model_id="model-v1",
            prompt_version="prompt-v1",
            policy_version=None,
            rag_corpus_version=None,
        ),
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
    )


def license_result(
    job_id: str,
    revision: str,
    started_at: datetime,
    *,
    coverage: AnalysisCoverage = AnalysisCoverage.COMPLETE,
) -> AnalysisResult:
    evidence = Evidence(
        evidence_id="package-1",
        evidence_type=EvidenceType.PACKAGE_METADATA,
        excerpt="Package declares GPL-3.0-only.",
        reference="https://example.invalid/packages/example/1.2.3",
        metadata_safe={"source": "registry"},
    )
    return AnalysisResult(
        contract_version="1",
        analysis_job_id=job_id,
        artifact_id="artifact-1",
        revision=revision,
        analysis_type=AnalysisType.LICENSE,
        status=AnalysisStatus.SUCCEEDED,
        coverage=coverage,
        candidates=[
            LicenseCandidate(
                ecosystem="NPM",
                normalized_package_name="Example-Package",
                resolved_version="1.2.3",
                normalized_license_expression="gpl-3.0-only",
                policy_outcome=LicensePolicyOutcome.POLICY_CONFLICT,
                evidence_ids=[evidence.evidence_id],
                uncertainty_flags=[],
            )
        ],
        evidence=[evidence],
        provider_failures=[],
        versions=AnalysisVersions(
            analyzer_version="license-v1",
            model_id=None,
            prompt_version=None,
            policy_version="license-policy-v1",
            rag_corpus_version=None,
        ),
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
    )


def make_service(store: InMemoryControlStore) -> AnalysisResultIntakeService:
    return AnalysisResultIntakeService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(hours=1),
        retention_policy=EvidenceRetentionPolicy(
            max_excerpt_chars=60,
            max_reference_chars=200,
            max_metadata_chars=100,
        ),
    )


def test_authoritative_patent_result_creates_minimal_risk_history_and_notification() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="one",
            revision="revision-1",
        )
        result = patent_result(job_id, "revision-1", started_at)
        acceptance = await make_service(store).accept_analysis_result(result)
        assert acceptance.disposition is AnalysisResultDisposition.ACCEPTED
        assert acceptance.job_status is AnalysisJobStatus.SUCCEEDED
        assert acceptance.evidence_count == 1
        assert len(acceptance.affected_risk_ids) == 1

        async with store() as uow:
            risks = await uow.risks.list_for_artifact(
                "artifact-1", AnalysisType.PATENT
            )
            assert len(risks) == 1
            risk = risks[0]
            assert risk.lifecycle_state is RiskLifecycleState.NEW
            assert risk.review_priority is ReviewPriority.HIGH
            evidence = await uow.risks.list_evidence(risk.id)
            events = await uow.risks.list_events(risk.id)
            assert len(evidence) == 1
            assert REDACTION_PLACEHOLDER in evidence[0].excerpt
            assert "secret-value" not in evidence[0].excerpt
            assert evidence[0].reference == "https://example.invalid/patent/1#claim-1"
            assert evidence[0].metadata_safe["access_token"] == REDACTION_PLACEHOLDER
            assert [event.event_type for event in events] == [RiskEventType.DETECTED]
            notifications = await uow.notifications.list_for_user("owner-1")
            assert len(notifications) == 1
            assert notifications[0].notification_type is NotificationType.RISK_HIGH_DETECTED
            job = await uow.analysis_jobs.get(job_id)
            event = await uow.change_events.get(f"change-one")
            state = await uow.artifacts.get_state("artifact-1")
            assert job is not None and job.status is AnalysisJobStatus.SUCCEEDED
            assert result.analysis_type in job.analysis_outcomes
            assert event is not None and event.status is ChangeEventStatus.DONE
            assert state is not None
            assert state.latest_successful_analysis_revision_by_type[
                AnalysisType.PATENT
            ] == "revision-1"

    run(scenario())


def test_duplicate_result_is_harmless_and_conflicting_result_is_rejected() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="duplicate",
            revision="revision-1",
        )
        service = make_service(store)
        result = patent_result(job_id, "revision-1", started_at)
        first = await service.accept_analysis_result(result)
        duplicate = await service.accept_analysis_result(result)
        assert duplicate.disposition is AnalysisResultDisposition.DUPLICATE
        assert duplicate.result_fingerprint == first.result_fingerprint

        conflicting = patent_result(
            job_id,
            "revision-1",
            started_at,
            title="A different canonical result",
        )
        with pytest.raises(AnalysisResultIntakeError, match="different canonical"):
            await service.accept_analysis_result(conflicting)
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert len(await uow.risks.list_evidence(risk.id)) == 1
            assert len(await uow.risks.list_events(risk.id)) == 1
            assert len(await uow.notifications.list_for_user("owner-1")) == 1

    run(scenario())


def test_authoritative_lifecycle_existing_resolved_and_reopened_preserves_review() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job1, started1 = await add_running_job(
            store, suffix="life-1", revision="revision-1", offset_seconds=0
        )
        await service.accept_analysis_result(
            patent_result(job1, "revision-1", started1, priority=ReviewPriority.MEDIUM)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            await uow.risks.save(
                replace(
                    risk,
                    review_disposition=ReviewDisposition.EXCLUDED,
                    review_version=risk.review_version + 1,
                )
            )
            await uow.commit()

        job2, started2 = await add_running_job(
            store, suffix="life-2", revision="revision-2", offset_seconds=10
        )
        await service.accept_analysis_result(
            patent_result(job2, "revision-2", started2, priority=ReviewPriority.HIGH)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.EXISTING
            assert risk.review_disposition is ReviewDisposition.EXCLUDED
            assert RiskEventType.PRIORITY_CHANGED in {
                event.event_type for event in await uow.risks.list_events(risk.id)
            }

        job3, started3 = await add_running_job(
            store, suffix="life-3", revision="revision-3", offset_seconds=20
        )
        resolved = await service.accept_analysis_result(
            patent_result(
                job3,
                "revision-3",
                started3,
                include_candidate=False,
            )
        )
        assert len(resolved.resolved_risk_ids) == 1
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.RESOLVED
            assert risk.review_disposition is ReviewDisposition.EXCLUDED

        job4, started4 = await add_running_job(
            store, suffix="life-4", revision="revision-4", offset_seconds=30
        )
        await service.accept_analysis_result(
            patent_result(job4, "revision-4", started4)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.EXISTING
            assert risk.review_disposition is ReviewDisposition.EXCLUDED
            events = await uow.risks.list_events(risk.id)
            assert RiskEventType.RESOLVED in {event.event_type for event in events}
            assert RiskEventType.REOPENED in {event.event_type for event in events}
            notifications = await uow.notifications.list_for_user("owner-1")
            assert NotificationType.RISK_REOPENED in {
                item.notification_type for item in notifications
            }

    run(scenario())


@pytest.mark.parametrize(
    ("status", "coverage", "failures", "expected_job_status"),
    (
        (
            AnalysisStatus.FAILED,
            AnalysisCoverage.NONE,
            [
                ProviderFailure(
                    provider="KIPRIS",
                    category="TIMEOUT",
                    retryable=True,
                    safe_message="API_KEY=provider-secret",
                )
            ],
            AnalysisJobStatus.FAILED,
        ),
        (
            AnalysisStatus.INCONCLUSIVE,
            AnalysisCoverage.NONE,
            [],
            AnalysisJobStatus.INCONCLUSIVE,
        ),
        (
            AnalysisStatus.SUCCEEDED,
            AnalysisCoverage.PARTIAL,
            [],
            AnalysisJobStatus.INCONCLUSIVE,
        ),
        (
            AnalysisStatus.SKIPPED,
            AnalysisCoverage.NONE,
            [],
            AnalysisJobStatus.INCONCLUSIVE,
        ),
    ),
)
def test_non_authoritative_results_never_change_or_resolve_existing_risk(
    status: AnalysisStatus,
    coverage: AnalysisCoverage,
    failures: list[ProviderFailure],
    expected_job_status: AnalysisJobStatus,
) -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        initial_job, initial_started = await add_running_job(
            store, suffix="initial", revision="revision-1", offset_seconds=0
        )
        await service.accept_analysis_result(
            patent_result(initial_job, "revision-1", initial_started)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            original_evidence = await uow.risks.list_evidence(risk.id)
            original_events = await uow.risks.list_events(risk.id)

        job_id, started_at = await add_running_job(
            store, suffix=f"non-auth-{status.value}", revision="revision-2", offset_seconds=10
        )
        result = patent_result(
            job_id,
            "revision-2",
            started_at,
            status=status,
            coverage=coverage,
            include_candidate=False,
            provider_failures=failures,
        )
        acceptance = await service.accept_analysis_result(result)
        assert acceptance.job_status is expected_job_status
        assert acceptance.affected_risk_ids == ()
        assert acceptance.resolved_risk_ids == ()
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.NEW
            assert await uow.risks.list_evidence(risk.id) == original_evidence
            assert await uow.risks.list_events(risk.id) == original_events
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None
            if status is AnalysisStatus.FAILED:
                outcome = job.analysis_outcomes[AnalysisType.PATENT]
                assert REDACTION_PLACEHOLDER in outcome.provider_failures[0].safe_message
                assert "provider-secret" not in outcome.provider_failures[0].safe_message
                assert len(await uow.audit.list_for_workspace("vws-1")) == 1

    run(scenario())


def test_multi_analyzer_job_waits_for_all_results_and_aggregates_inconclusive() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="multi",
            revision="revision-1",
            requested=(AnalysisType.PATENT, AnalysisType.LICENSE),
        )
        service = make_service(store)
        first = await service.accept_analysis_result(
            patent_result(job_id, "revision-1", started_at)
        )
        assert first.job_status is AnalysisJobStatus.RUNNING
        async with store() as uow:
            event = await uow.change_events.get("change-multi")
            assert event is not None and event.status is ChangeEventStatus.PROCESSING

        second = await service.accept_analysis_result(
            license_result(
                job_id,
                "revision-1",
                started_at,
                coverage=AnalysisCoverage.PARTIAL,
            )
        )
        assert second.job_status is AnalysisJobStatus.INCONCLUSIVE
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            event = await uow.change_events.get("change-multi")
            license_risks = await uow.risks.list_for_artifact(
                "artifact-1", AnalysisType.LICENSE
            )
            assert job is not None and set(job.analysis_outcomes) == {
                AnalysisType.PATENT,
                AnalysisType.LICENSE,
            }
            assert event is not None and event.status is ChangeEventStatus.DONE
            assert license_risks == ()

    run(scenario())


def test_authoritative_license_result_uses_normalized_stable_identity() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="license",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        await make_service(store).accept_analysis_result(
            license_result(job_id, "revision-1", started_at)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE)
            )[0]
            assert risk.risk_key == license_risk_key(
                "artifact-1",
                "npm",
                "example-package",
                "1.2.3",
                "GPL-3.0-ONLY",
            )
            assert risk.review_priority is ReviewPriority.HIGH

    run(scenario())


def test_unrequested_or_stale_result_rolls_back_without_outcome_or_risk() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="stale",
            revision="revision-1",
        )
        async with store() as uow:
            state = await uow.artifacts.get_state("artifact-1")
            assert state is not None
            await uow.artifacts.save_state(
                replace(state, latest_revision="revision-2", updated_at=NOW + timedelta(minutes=1))
            )
            await uow.commit()
        with pytest.raises(AnalysisResultIntakeError, match="no longer canonical"):
            await make_service(store).accept_analysis_result(
                patent_result(job_id, "revision-1", started_at)
            )
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None and not job.analysis_outcomes
            assert await uow.risks.list_for_artifact(
                "artifact-1", AnalysisType.PATENT
            ) == ()

    run(scenario())


def test_inconsistent_change_event_revision_is_rejected_before_result_intake() -> None:
    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="context-mismatch",
            revision="revision-1",
        )
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None
            event = await uow.change_events.get(job.change_event_id)
            assert event is not None
            await uow.change_events.save(
                replace(
                    event,
                    revision="revision-corrupt",
                    source_change=event.source_change.model_copy(
                        update={"revision": "revision-corrupt"}
                    ),
                )
            )
            await uow.commit()

        with pytest.raises(AnalysisResultIntakeError, match="context is inconsistent"):
            await make_service(store).accept_analysis_result(
                patent_result(job_id, "revision-1", started_at)
            )

        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None and not job.analysis_outcomes
            assert await uow.risks.list_for_artifact(
                "artifact-1", AnalysisType.PATENT
            ) == ()

    run(scenario())
