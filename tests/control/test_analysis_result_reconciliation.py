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
    SupersededRevisionError,
)
from ip_risk_agent.application.risk_exclusion import exclude_artifact_risks
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
    quote_spans: dict | None = None,
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
                provider_metadata_safe={
                    "jurisdiction": "KR",
                    **({} if quote_spans is None else {"quote_spans": quote_spans}),
                },
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
                    review_disposition=ReviewDisposition.ACCEPTED_RISK,
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
            assert risk.review_disposition is ReviewDisposition.ACCEPTED_RISK
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
            assert risk.review_disposition is ReviewDisposition.ACCEPTED_RISK

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
            assert risk.review_disposition is ReviewDisposition.ACCEPTED_RISK
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
            # 부분적으로 본 결과도 **본 것은 적는다.** 예전에는 여기가 비어 있었고,
            # 그래서 한 패키지 조회 실패가 그 파일 전체를 없던 일로 만들었다.
            assert len(license_risks) == 1
            assert license_risks[0].lifecycle_state is RiskLifecycleState.NEW

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
        # 결함이 아니라 소스가 앞서 나간 것이다. 파이프라인이 그 둘을 구분해
        # 사용자에게 다른 안내를 낼 수 있도록 종류를 나눠 둔다.
        with pytest.raises(SupersededRevisionError, match="no longer canonical"):
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


def test_an_excluded_risk_is_revived_as_new_and_unreviewed() -> None:
    """추적이 끊겨 제외됐던 파일이 다시 대상이 되면 이전 Risk 를 되살린다.

    새로 만들지 않는 이유는 그 파일의 이력이 한 줄로 이어져야 하기 때문이다. 다만
    제외되어 있던 동안의 판단은 더 이상 유효하지 않으므로 NEW / UNREVIEWED 에서
    다시 시작한다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(store, suffix="revive-1", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(job1, "revision-1", started1, priority=ReviewPriority.MEDIUM)
        )

        # 추적을 끊었을 때와 같은 상태를 만든다.
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            await uow.risks.save(
                replace(
                    risk,
                    lifecycle_state=RiskLifecycleState.RESOLVED,
                    review_disposition=ReviewDisposition.EXCLUDED,
                    review_version=risk.review_version + 1,
                    resolved_at=risk.last_seen_at,
                )
            )
            await uow.commit()
            excluded_id = risk.id

        job2, started2 = await add_running_job(
            store, suffix="revive-2", revision="revision-2", offset_seconds=10
        )
        await service.accept_analysis_result(
            patent_result(job2, "revision-2", started2, priority=ReviewPriority.HIGH)
        )

        async with store() as uow:
            risks = await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            assert len(risks) == 1, "되살릴 때 Risk 를 새로 만들면 이력이 끊긴다"
            revived = risks[0]
            assert revived.id == excluded_id
            assert revived.lifecycle_state is RiskLifecycleState.NEW
            assert revived.review_disposition is ReviewDisposition.UNREVIEWED
            assert revived.resolved_at is None

    run(scenario())


def test_an_accepted_risk_is_not_reset_when_analysis_runs_again() -> None:
    """사람이 내린 처분은 재분석이 덮지 않는다. 되살리기는 EXCLUDED 에만 적용된다."""

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(store, suffix="keep-1", revision="revision-1")
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
                    review_disposition=ReviewDisposition.ACCEPTED_RISK,
                    review_version=risk.review_version + 1,
                )
            )
            await uow.commit()

        job2, started2 = await add_running_job(
            store, suffix="keep-2", revision="revision-2", offset_seconds=10
        )
        await service.accept_analysis_result(
            patent_result(job2, "revision-2", started2, priority=ReviewPriority.HIGH)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.review_disposition is ReviewDisposition.ACCEPTED_RISK
            assert risk.lifecycle_state is RiskLifecycleState.EXISTING

    run(scenario())


def test_untracking_archives_the_artifact_and_excludes_its_risks() -> None:
    """추적 해제는 지우지 않는다. 닫고 남긴다.

    사용자가 스스로 내린 처분이 아니라 추적이 끊겨 관리가 끝난 것이므로
    ACCEPTED_RISK 가 아니라 EXCLUDED 다. 근거와 이력은 그대로 남아야 감사가 된다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job, started = await add_running_job(store, suffix="untrack-1", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(job, "revision-1", started, priority=ReviewPriority.MEDIUM)
        )
        async with store() as uow:
            before = await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            evidence_before = await uow.risks.list_evidence(before[0].id)
        assert before and evidence_before

        async with store() as uow:
            excluded = await exclude_artifact_risks(
                uow,
                risk_workspace_id="vws-1",
                artifact_id="artifact-1",
                occurred_at=NOW + timedelta(minutes=5),
                reason_safe="artifact tracking was stopped",
                id_factory=lambda prefix: f"{prefix}-untrack-1",
            )
            await uow.commit()
        assert excluded == [before[0].id]

        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.RESOLVED
            assert risk.review_disposition is ReviewDisposition.EXCLUDED
            assert risk.review_version == before[0].review_version + 1
            # 지우지 않는다.
            assert len(await uow.risks.list_evidence(risk.id)) == len(evidence_before)
            assert any(
                event.event_type is RiskEventType.REVIEW_DISPOSITION_CHANGED
                for event in await uow.risks.list_events(risk.id)
            )

    run(scenario())


def test_excluding_twice_does_not_pile_up_history() -> None:
    """같은 mount 를 두 번 일시중지해도 이력이 부풀지 않는다."""

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job, started = await add_running_job(store, suffix="twice-1", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(job, "revision-1", started, priority=ReviewPriority.MEDIUM)
        )
        for attempt in range(2):
            async with store() as uow:
                await exclude_artifact_risks(
                    uow,
                    risk_workspace_id="vws-1",
                    artifact_id="artifact-1",
                    occurred_at=NOW + timedelta(minutes=5 + attempt),
                    reason_safe="artifact tracking was stopped",
                    id_factory=lambda prefix, n=attempt: f"{prefix}-twice-{n}",
                )
                await uow.commit()
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            disposition_events = [
                event
                for event in await uow.risks.list_events(risk.id)
                if event.event_type is RiskEventType.REVIEW_DISPOSITION_CHANGED
            ]
            assert len(disposition_events) == 1

    run(scenario())


def test_a_low_grade_candidate_never_becomes_a_risk() -> None:
    """검토 우선도 '하' 는 낮은 위험이 아니라 관리 대상이 아니라는 판정이다.

    눈금의 아래쪽 전부가 '하' 이고 그 끝은 "전혀 risk 아님" 이다. 그런 후보로 Risk 를
    만들면 목록이 관리할 필요 없는 것으로 채워진다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job, started = await add_running_job(store, suffix="low-1", revision="revision-1")
        receipt = await service.accept_analysis_result(
            patent_result(job, "revision-1", started, priority=ReviewPriority.LOW)
        )
        assert receipt.affected_risk_ids == ()
        async with store() as uow:
            assert await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT) == ()

    run(scenario())


def test_a_risk_resolves_when_it_falls_to_the_low_grade() -> None:
    """상·중을 유지하면 EXISTING, '하' 로 내려가면 비로소 RESOLVED 다.

    사용자는 그렇게 닫힌 Risk 를 확인하고 받아들이게 된다. 이것이 유사도 임계값을
    두 개 두려는 이유다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(store, suffix="fall-1", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(job1, "revision-1", started1, priority=ReviewPriority.HIGH)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.NEW

        # 상 -> 중 은 여전히 Risk 다. 존재가 이어진다.
        job2, started2 = await add_running_job(
            store, suffix="fall-2", revision="revision-2", offset_seconds=10
        )
        await service.accept_analysis_result(
            patent_result(job2, "revision-2", started2, priority=ReviewPriority.MEDIUM)
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.EXISTING
            assert risk.review_priority is ReviewPriority.MEDIUM

        # 중 -> 하 에서 닫힌다.
        job3, started3 = await add_running_job(
            store, suffix="fall-3", revision="revision-3", offset_seconds=20
        )
        resolved = await service.accept_analysis_result(
            patent_result(job3, "revision-3", started3, priority=ReviewPriority.LOW)
        )
        assert len(resolved.resolved_risk_ids) == 1
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.RESOLVED
            # 지우지 않는다. 사용자가 확인하고 받아들일 대상으로 남는다.
            assert risk.review_disposition is ReviewDisposition.UNREVIEWED

    run(scenario())


def test_a_non_authoritative_low_result_does_not_close_a_risk() -> None:
    """'하' 는 알아보고 내린 판정이고, 'INCONCLUSIVE' 는 알아보지 못한 것이다.

    둘을 섞으면 provider 조회가 실패했을 뿐인데 Risk 가 해결된 것처럼 닫힌다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job1, started1 = await add_running_job(store, suffix="unk-1", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(job1, "revision-1", started1, priority=ReviewPriority.HIGH)
        )
        job2, started2 = await add_running_job(
            store, suffix="unk-2", revision="revision-2", offset_seconds=10
        )
        await service.accept_analysis_result(
            patent_result(
                job2,
                "revision-2",
                started2,
                priority=ReviewPriority.LOW,
                coverage=AnalysisCoverage.PARTIAL,
            )
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            assert risk.lifecycle_state is RiskLifecycleState.NEW

    run(scenario())


def test_a_verified_quote_span_reaches_the_stored_evidence() -> None:
    """근거는 문단까지 좁혀져 있고, 그 안의 어느 문장인지는 구간이 짚는다.

    화면은 저장된 발췌를 보여 주고 그 구간만 강조한다. 구간이 canonical 까지
    오지 않으면 하이라이트가 가리킬 것이 없다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job, started = await add_running_job(store, suffix="span-1", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(
                job,
                "revision-1",
                started,
                quote_spans={"evidence-1": {"start": 3, "end": 11}},
            )
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            evidence = await uow.risks.list_evidence(risk.id)
        stored = {item.evidence_id_from_result: item for item in evidence}
        assert stored["evidence-1"].metadata_safe["quote_start"] == 3
        assert stored["evidence-1"].metadata_safe["quote_end"] == 11

    run(scenario())


def test_a_malformed_quote_span_is_dropped_instead_of_stored() -> None:
    """canonical 은 provider metadata 를 믿지 않는다.

    잘못된 구간으로 엉뚱한 곳을 강조하면 사람이 그것을 근거로 읽는다. 강조가 없는
    것보다 나쁘다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job, started = await add_running_job(store, suffix="span-2", revision="revision-1")
        await service.accept_analysis_result(
            patent_result(
                job,
                "revision-1",
                started,
                quote_spans={
                    "evidence-1": {"start": 9, "end": 4},  # 끝이 시작보다 앞
                    "evidence-2": {"start": -1, "end": 5},  # 음수
                    "evidence-3": "구간이 아니다",
                },
            )
        )
        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            evidence = await uow.risks.list_evidence(risk.id)
        for item in evidence:
            assert "quote_start" not in item.metadata_safe
            assert "quote_end" not in item.metadata_safe

    run(scenario())


async def _reanalyze(store: InMemoryControlStore, job_id: str, suffix: str) -> datetime:
    """제품의 "다시 검사" 와 같은 방식으로 되돌린 뒤 다시 점유한다."""
    from ip_risk_agent.application.analysis_jobs.transitions import (
        claim_analysis_job,
        reanalyze_analysis_job,
    )
    from ip_risk_agent.application.process_change.transitions import (
        claim_change_event,
        reanalyze_change_event,
    )

    started_at = NOW + timedelta(minutes=5)
    async with store() as uow:
        job = await uow.analysis_jobs.get(job_id)
        event = await uow.change_events.get(f"change-{suffix}")
        assert job is not None and event is not None
        event = reanalyze_change_event(event, occurred_at=started_at)
        job = reanalyze_analysis_job(job)
        event = claim_change_event(
            event,
            occurred_at=started_at,
            lease_expires_at=started_at + timedelta(minutes=5),
        )
        job = claim_analysis_job(job, occurred_at=started_at)
        await uow.change_events.save(event)
        await uow.analysis_jobs.save(job)
        await uow.commit()
    return started_at


def test_reanalyzing_an_unchanged_document_does_not_collide_with_its_own_evidence() -> None:
    """배포에서 재검사가 매번 이것으로 실패했다.

    근거 문서 ID 는 (Risk, 분석 실행, 근거 이름) 에서 결정된다. 재검사는 같은
    분석 실행을 다시 돌리므로 ID 도 같아진다. 실행 결과는 되돌릴 때 지워지는데
    근거는 남아 있어, 같은 ID 를 다시 만들려다 고유키 위반으로 죽었다. 화면에는
    ``INTERNAL:UNEXPECTED_PIPELINE_FAILURE`` 만 보였다.

    이력과 알림도 결과 지문에서 ID 가 나오므로 같은 함정이 있다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store, suffix="again", revision="revision-1"
        )
        service = make_service(store)
        first = await service.accept_analysis_result(
            patent_result(job_id, "revision-1", started_at)
        )
        assert first.disposition is AnalysisResultDisposition.ACCEPTED

        restarted_at = await _reanalyze(store, job_id, "again")
        second = await service.accept_analysis_result(
            patent_result(job_id, "revision-1", restarted_at)
        )
        assert second.disposition is AnalysisResultDisposition.ACCEPTED

        async with store() as uow:
            risks = await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            # 바뀐 것이 없으므로 Risk 도 하나 그대로다.
            assert len(risks) == 1
            evidence = await uow.risks.list_evidence(risks[0].id)
            # 근거가 두 배로 늘어서도 안 된다.
            assert len(evidence) == 1
            notifications = await uow.notifications.list_for_user("owner-1")
            assert len(notifications) == 1

    run(scenario())


def test_reanalysis_replaces_the_evidence_that_run_recorded_before() -> None:
    """다시 검사하면 그 실행의 근거는 이번 것으로 바뀌어야 한다.

    지난번 것을 남겨 두면 화면이 이번 판정과 다른 구간을 강조한다. 사람은 그것을
    근거로 읽는다.

    해소된 Risk 의 근거는 여기서 다루지 않는다 — 왜 위험이었는지의 기록이므로
    남는 것이 맞다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)
        job_id, started_at = await add_running_job(
            store, suffix="span-again", revision="revision-1"
        )
        await service.accept_analysis_result(
            patent_result(
                job_id,
                "revision-1",
                started_at,
                quote_spans={"evidence-1": {"start": 3, "end": 11}},
            )
        )

        restarted_at = await _reanalyze(store, job_id, "span-again")
        await service.accept_analysis_result(
            patent_result(
                job_id,
                "revision-1",
                restarted_at,
                quote_spans={"evidence-1": {"start": 5, "end": 20}},
            )
        )

        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
            )[0]
            evidence = await uow.risks.list_evidence(risk.id)
        assert len(evidence) == 1
        assert evidence[0].metadata_safe["quote_start"] == 5
        assert evidence[0].metadata_safe["quote_end"] == 20

    run(scenario())


def test_a_document_no_analyzer_handles_finishes_rather_than_looking_unfinished() -> None:
    """회의록이나 기술 내용이 없는 README 는 판정할 후보가 없다.

    예전에는 그런 실행이 INCONCLUSIVE 로 끝나 화면에 "일부 후보를 판정하지
    못했습니다" 가 떴다. 판정하지 못한 것이 아니라 판정할 것이 없었다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store, suffix="skipped", revision="revision-1"
        )
        acceptance = await make_service(store).accept_analysis_result(
            patent_result(
                job_id,
                "revision-1",
                started_at,
                status=AnalysisStatus.SKIPPED,
                coverage=AnalysisCoverage.NONE,
                include_candidate=False,
            )
        )

        # 상태는 미판정이다 — 권위 있는 결과가 아니므로 기존 Risk 를 건드리지
        # 않아야 하고, 그 규칙을 상태가 지킨다.
        assert acceptance.job_status is AnalysisJobStatus.INCONCLUSIVE
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None
            # 다만 사유는 달라야 한다. "판정하지 못했다" 가 아니라 "판정할 것이
            # 없었다" 이고, 화면이 그 둘에 다른 안내를 낸다.
            assert job.failure_safe == "ANALYSIS:NOT_APPLICABLE"

    run(scenario())


# --------------------------------------------------------------------- 0-L


def test_a_broken_read_cannot_resolve_a_dependency_files_risks() -> None:
    """읽기가 망가진 결과가 위험을 "해소" 로 바꾸지 못한다.

    의존성 파일을 읽다가 망가지면 결과가 **선언 0 건**으로 나온다. 조각화도, redaction
    도, 파서가 삼킨 실패도, 게이트의 절단도 전부 같은 모양이다. 그리고 0 건은 실패가
    아니라 ``SUCCEEDED`` + ``COMPLETE`` 로 올라와 권위를 얻는다. 그러면 그 파일의 Risk 가
    전부 닫히고 알림은 0 건이다 — 위험을 놓치는 것이 아니라 **사라졌다고 오보한다.**

    그래서 길마다 막지 않고 결말 하나를 막는다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(
            store,
            suffix="zero-1",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        await service.accept_analysis_result(
            license_result(job1, "revision-1", started1)
        )
        async with store() as uow:
            risks = await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE)
            assert len(risks) == 1
            assert risks[0].lifecycle_state is RiskLifecycleState.NEW

        # 읽기가 망가진 결과다. 네 손실 경로가 전부 여기로 온다 — 못 읽었거나 잘렸으면
        # coverage 가 PARTIAL 이고, 그 0 건은 "없다" 가 아니라 "모른다" 다.
        job2, started2 = await add_running_job(
            store,
            suffix="zero-2",
            revision="revision-2",
            requested=(AnalysisType.LICENSE,),
            offset_seconds=10,
        )
        emptied = license_result(
            job2, "revision-2", started2, coverage=AnalysisCoverage.PARTIAL
        ).model_copy(update={"candidates": [], "evidence": []})
        assert emptied.status is AnalysisStatus.SUCCEEDED

        acceptance = await service.accept_analysis_result(emptied)
        assert not acceptance.resolved_risk_ids

        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE)
            )[0]
            assert risk.lifecycle_state is not RiskLifecycleState.RESOLVED
            assert risk.resolved_at is None
            assert RiskEventType.RESOLVED not in {
                event.event_type for event in await uow.risks.list_events(risk.id)
            }

    run(scenario())


def test_a_package_removed_from_a_readable_manifest_still_resolves() -> None:
    """막는 것은 "통째로 0 건" 하나뿐이다.

    선언이 하나라도 나왔다면 파일은 제대로 읽혔고, 그중 어떤 패키지가 목록에서 빠진 것은
    **사람이 실제로 그 의존성을 지운 것**이다. 그것까지 막으면 정상적인 제거가 영영
    검토 대기에 남는다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(
            store,
            suffix="kept-1",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        first = license_result(job1, "revision-1", started1)
        second_candidate = first.candidates[0].model_copy(
            update={"normalized_package_name": "Other-Package"}
        )
        await service.accept_analysis_result(
            first.model_copy(update={"candidates": [*first.candidates, second_candidate]})
        )
        async with store() as uow:
            assert (
                len(await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE))
                == 2
            )

        # 둘 중 하나만 남았다. 파일은 읽혔으므로 사라진 쪽은 진짜로 지워진 것이다.
        job2, started2 = await add_running_job(
            store,
            suffix="kept-2",
            revision="revision-2",
            requested=(AnalysisType.LICENSE,),
            offset_seconds=10,
        )
        acceptance = await service.accept_analysis_result(
            license_result(job2, "revision-2", started2)
        )
        assert len(acceptance.resolved_risk_ids) == 1

    run(scenario())


def test_a_patent_document_with_no_candidates_still_resolves() -> None:
    """0-L 은 의존성 경로에만 건다.

    문서에서 특허 후보가 사라지는 것은 파싱 손실이 아니라 판정 변화다. 그쪽을 함께 막으면
    정상적인 해소가 전부 멈춘다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(
            store, suffix="pat-1", revision="revision-1"
        )
        await service.accept_analysis_result(patent_result(job1, "revision-1", started1))

        job2, started2 = await add_running_job(
            store, suffix="pat-2", revision="revision-2", offset_seconds=10
        )
        emptied = patent_result(job2, "revision-2", started2).model_copy(
            update={"candidates": [], "evidence": []}
        )
        acceptance = await service.accept_analysis_result(emptied)
        assert len(acceptance.resolved_risk_ids) == 1

    run(scenario())


# --------------------------------------------------------------------- 0-E


def test_a_partial_result_records_risks_but_cannot_close_them() -> None:
    """`PARTIAL` 이 막는 것은 **해소 하나**다.

    예전에는 하나였다 — `PARTIAL` 이면 reconcile 전체가 건너뛰어져 Risk 생성도 근거도
    이력도 없었다. 그래서 스무 개를 읽고 그중 한 패키지의 조회가 실패하면 스무 개가
    전부 버려졌다. RAG 가 죽었을 때도 같아서, **검색 장애가 정책 표의 판정까지 버렸다.**
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        # 온전한 결과로 Risk 를 만든다.
        job1, started1 = await add_running_job(
            store,
            suffix="partial-1",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        first = license_result(job1, "revision-1", started1)
        second_candidate = first.candidates[0].model_copy(
            update={"normalized_package_name": "Other-Package"}
        )
        await service.accept_analysis_result(
            first.model_copy(update={"candidates": [*first.candidates, second_candidate]})
        )
        async with store() as uow:
            assert (
                len(await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE))
                == 2
            )

        # 다음 실행은 하나만 보고 부분적으로 끝났다.
        job2, started2 = await add_running_job(
            store,
            suffix="partial-2",
            revision="revision-2",
            requested=(AnalysisType.LICENSE,),
            offset_seconds=10,
        )
        acceptance = await service.accept_analysis_result(
            license_result(
                job2, "revision-2", started2, coverage=AnalysisCoverage.PARTIAL
            )
        )

        # 본 것은 적혔다.
        assert acceptance.affected_risk_ids
        # 못 본 것은 닫지 못한다 — 사라진 쪽은 그대로 열려 있다.
        assert not acceptance.resolved_risk_ids
        async with store() as uow:
            risks = await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE)
            assert len(risks) == 2
            assert all(
                risk.lifecycle_state is not RiskLifecycleState.RESOLVED for risk in risks
            )

    run(scenario())


def test_a_partial_result_does_not_count_as_having_analysed_the_revision() -> None:
    """부분적으로 본 것을 성공한 분석으로 적으면 다시 볼 이유가 사라진다."""

    async def scenario() -> None:
        store = await seed_artifact_context()
        job_id, started_at = await add_running_job(
            store,
            suffix="partial-rev",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        await make_service(store).accept_analysis_result(
            license_result(
                job_id, "revision-1", started_at, coverage=AnalysisCoverage.PARTIAL
            )
        )
        async with store() as uow:
            state = await uow.artifacts.get_state("artifact-1")
            assert AnalysisType.LICENSE not in (
                state.latest_successful_analysis_revision_by_type
            )

    run(scenario())


def test_a_manifest_emptied_on_purpose_does_resolve() -> None:
    """사람이 의존성을 전부 지웠다면 해소되는 것이 맞다.

    ``COMPLETE`` + 0 건은 이제 "온전히 읽었고 정말 아무것도 선언하지 않았다" 를 뜻한다 —
    네 손실 경로가 모두 ``PARTIAL`` 로 가게 된 뒤에 성립하는 구분이다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(
            store,
            suffix="emptied-1",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        await service.accept_analysis_result(
            license_result(job1, "revision-1", started1)
        )

        job2, started2 = await add_running_job(
            store,
            suffix="emptied-2",
            revision="revision-2",
            requested=(AnalysisType.LICENSE,),
            offset_seconds=10,
        )
        acceptance = await service.accept_analysis_result(
            license_result(job2, "revision-2", started2).model_copy(
                update={"candidates": [], "evidence": []}
            )
        )
        assert len(acceptance.resolved_risk_ids) == 1

    run(scenario())


# --------------------------------------------------------------------- 결함 22


def test_old_evidence_survives_for_the_ledger_but_not_for_the_verdict() -> None:
    """근거는 실행마다 쌓인다. 그런데 **지금 판정 옆에 서면 안 된다.**

    ``clear_evidence`` 가 같은 실행의 행만 지우는 것은 의도다 — 이력
    (``RiskEvent.evidence_refs``)이 옛 행을 가리키므로, 지우면 "그때 무엇을 보고 그렇게
    판단했는가" 를 되짚을 수 없다.

    대신 읽을 때 건다. 안 걸면 옛 corpus 판본에서 나온 조각이 현재 판정 옆에 나란히 서고,
    판정에 적힌 ``rag_corpus_version`` 과 근거가 서로 다른 시점을 가리킨다.
    """

    async def scenario() -> None:
        store = await seed_artifact_context()
        service = make_service(store)

        job1, started1 = await add_running_job(
            store,
            suffix="evi-1",
            revision="revision-1",
            requested=(AnalysisType.LICENSE,),
        )
        await service.accept_analysis_result(
            license_result(job1, "revision-1", started1)
        )

        job2, started2 = await add_running_job(
            store,
            suffix="evi-2",
            revision="revision-2",
            requested=(AnalysisType.LICENSE,),
            offset_seconds=10,
        )
        await service.accept_analysis_result(
            license_result(job2, "revision-2", started2)
        )

        async with store() as uow:
            risk = (
                await uow.risks.list_for_artifact("artifact-1", AnalysisType.LICENSE)
            )[0]
            assert risk.latest_analysis_job_id == job2

            everything = await uow.risks.list_evidence(risk.id)
            current = await uow.risks.list_evidence(
                risk.id, analysis_job_id=risk.latest_analysis_job_id
            )

            # 이력을 위해 옛 행이 남아 있다.
            assert {item.analysis_job_id for item in everything} == {job1, job2}
            # 지금 판정이 보는 것은 이번 실행뿐이다.
            assert {item.analysis_job_id for item in current} == {job2}
            assert len(current) < len(everything)

    run(scenario())
