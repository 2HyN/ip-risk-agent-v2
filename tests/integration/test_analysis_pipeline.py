from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from iprisk_contracts import (
    AnalysisCoverage,
    AnalysisResult,
    AnalysisStatus,
    AnalysisType,
    AnalysisVersions,
    ArtifactKind,
    ChangeType,
    ContentScope,
    Evidence,
    EvidenceType,
    PatentCandidate,
    ReviewPriority,
    SegmentKind,
    SourceAccessReceipt,
    SourceAccessType,
    SourceArtifactRef,
    SourceChange,
    SourceSnapshot,
    SourceType,
    TextSegment,
)

from ip_risk_agent.application.analysis_jobs import AnalysisJobStatus
from ip_risk_agent.application.process_change import ChangeEventStatus
from ip_risk_agent.application.public_facade import SourceMetadataRegistrationCommand
from ip_risk_agent.composition.analyzer_completeness import CompleteIntelligenceFacade
from ip_risk_agent.composition.app import create_worker_app
from ip_risk_agent.composition.container import ContainerOverrides, build_container
from ip_risk_agent.composition.settings import AppRole, RuntimeProfile, Settings
from ip_risk_agent.composition.task_auth import StaticBearerTaskAuthenticator
from ip_risk_agent.connectors.common.errors import TemporaryUnavailableError
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

TASK_TOKEN = "phase-4-local-worker-task-token-at-least-32-characters"


def now() -> datetime:
    return datetime.now(UTC)


class FakeSourceAdapter:
    source_type = SourceType.GITHUB

    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.fetch_count = 0
        self.cleanup_count = 0
        self.cleanup_probe = None
        self.cleanup_observation = None

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot:
        self.fetch_count += 1
        if self.fail_once and self.fetch_count == 1:
            raise TemporaryUnavailableError(
                provider="github",
                safe_message="provider temporarily unavailable",
            )
        accessed_at = now()
        text = "def rank_candidates():\n    return True\n"
        return SourceSnapshot(
            contract_version="1",
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=change.source_type,
            source_artifact_id=change.artifact.source_artifact_id,
            resolved_revision=change.revision or "missing",
            retrieved_at=accessed_at,
            display_name=change.artifact.display_name,
            logical_path_hint=change.artifact.path_hint,
            mime_type="text/x-python",
            artifact_kind=ArtifactKind.SOURCE_CODE,
            content_scope=ContentScope.FULL_TEXT,
            text_segments=[
                TextSegment(
                    segment_id="full",
                    text=text,
                    line_start=1,
                    line_end=2,
                    segment_kind=SegmentKind.FULL,
                )
            ],
            checksum="sha256:source-revision-1",
            byte_size=len(text.encode()),
            source_access_receipt=SourceAccessReceipt(
                access_type=SourceAccessType.FULL_CONTENT,
                provider_request_id="provider-request-1",
                content_bytes=len(text.encode()),
                occurred_at=accessed_at,
            ),
        )

    async def resolve_original(self, artifact):  # pragma: no cover - other integration test
        raise NotImplementedError

    async def cleanup(self, change: SourceChange) -> None:
        try:
            if self.cleanup_probe is not None:
                self.cleanup_observation = await self.cleanup_probe(change)
        except Exception as exc:  # expose cleanup-time failures to the assertion
            self.cleanup_observation = exc
        finally:
            self.cleanup_count += 1


class FakeIntelligence:
    def __init__(self, *, omit_results: bool = False) -> None:
        self.omit_results = omit_results

    async def analyze(self, artifact) -> list[AnalysisResult]:
        assert artifact.requested_analyzers == [AnalysisType.PATENT]
        if self.omit_results:
            return []
        started = now()
        evidence = Evidence(
            evidence_id="patent-claim-1",
            evidence_type=EvidenceType.PATENT_CLAIM,
            excerpt="candidate ranking claim",
            reference="https://example.invalid/patent/1#claim-1",
            metadata_safe={},
        )
        return [
            AnalysisResult(
                contract_version="1",
                analysis_job_id=artifact.analysis_job_id,
                artifact_id=artifact.artifact_id,
                revision=artifact.revision,
                analysis_type=AnalysisType.PATENT,
                status=AnalysisStatus.SUCCEEDED,
                coverage=AnalysisCoverage.COMPLETE,
                candidates=[
                    PatentCandidate(
                        normalized_application_number="KR-10-2026-000001",
                        title="Candidate ranking method",
                        suggested_review_priority=ReviewPriority.HIGH,
                        matched_elements=["candidate ranking"],
                        evidence_ids=[evidence.evidence_id],
                        provider_metadata_safe={},
                    )
                ],
                evidence=[evidence],
                provider_failures=[],
                versions=AnalysisVersions(
                    analyzer_version="fake-patent-v1",
                    model_id="fake-model-v1",
                    prompt_version="fake-prompt-v1",
                ),
                started_at=started,
                completed_at=now(),
            )
        ]


def worker_settings() -> Settings:
    return Settings(
        profile=RuntimeProfile.TEST,
        role=AppRole.WORKER,
        log_level="INFO",
        public_base_url="http://testserver",
        session_secret="",
    )


async def seed_execution(container, *, fingerprint: str = "fingerprint-1"):
    observed = now()
    async with container.unit_of_work_factory() as uow:
        await uow.users.add(
            User(
                "owner-1",
                "owner-subject",
                "owner@example.com",
                "Owner",
                observed,
                observed,
            )
        )
        await uow.workspaces.add(
            RiskWorkspace(
                "vws-1",
                "Workspace",
                "owner-1",
                "security-v1",
                "retention-v1",
                observed,
                observed,
            )
        )
        await uow.memberships.add(
            Membership(
                membership_id_for("vws-1", "owner-1"),
                "vws-1",
                "owner-1",
                MembershipRole.OWNER,
                MembershipStatus.ACTIVE,
                "owner-1",
                observed,
                observed,
            )
        )
        await uow.commit()
    source = await container.control_facade.register_source_metadata(
        SourceMetadataRegistrationCommand(
            registration_key="github:install-1:repo-1:vws-1",
            actor_user_id="owner-1",
            risk_workspace_id="vws-1",
            source_type=SourceType.GITHUB,
            connection_key="install-1",
            source_workspace_key="acme/repo@main",
            external_scope_id="acme/repo@main",
            source_workspace_display_name="acme/repo",
            mount_alias="Repository",
            provider_subject="install-1",
        )
    )
    registered = await container.control_facade.register_source_change(
        SourceChange(
            contract_version="1",
            event_id=f"event-{fingerprint}",
            provider_event_id=f"delivery-{fingerprint}",
            event_fingerprint=fingerprint,
            risk_workspace_id="vws-1",
            mount_id=source.mount_id,
            source_workspace_id=source.source_workspace_id,
            source_type=SourceType.GITHUB,
            artifact=SourceArtifactRef(
                source_artifact_id="repo:path:src/main.py",
                display_name="main.py",
                path_hint="src/main.py",
            ),
            change_type=ChangeType.UPDATE,
            revision="revision-1",
            observed_at=observed,
            safe_metadata={"branch": "main"},
        )
    )
    return registered


def build_worker(*, adapter=None, intelligence=None):
    adapter = adapter or FakeSourceAdapter()
    delegate = intelligence or FakeIntelligence()
    complete = CompleteIntelligenceFacade(
        delegate,
        configured_analysis_types=(AnalysisType.PATENT, AnalysisType.LICENSE),
        active_analysis_types=(AnalysisType.PATENT, AnalysisType.LICENSE),
    )
    container = build_container(
        worker_settings(),
        overrides=ContainerOverrides(
            source_adapters=(adapter,),
            intelligence=complete,
            task_authenticator=StaticBearerTaskAuthenticator(TASK_TOKEN),
        ),
    )
    return container, adapter


def test_worker_runs_source_gate_analysis_to_terminal_risk_and_duplicate_noop() -> None:
    container, adapter = build_worker()
    registered = asyncio.run(seed_execution(container))
    with TestClient(create_worker_app(container)) as client:
        assert client.post(
            "/internal/tasks/analyze-change",
            json={"change_event_id": registered.change_event_id},
        ).status_code == 401
        response = client.post(
            "/internal/tasks/analyze-change",
            headers={"Authorization": f"Bearer {TASK_TOKEN}"},
            json={"change_event_id": registered.change_event_id},
        )
        assert response.status_code == 200
        assert response.json()["disposition"] == "COMPLETED"
        assert response.json()["terminal_job_status"] == "SUCCEEDED"
        duplicate = client.post(
            "/internal/tasks/analyze-change",
            headers={"Authorization": f"Bearer {TASK_TOKEN}"},
            json={"change_event_id": registered.change_event_id},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["disposition"] == "DUPLICATE"
        malformed = client.post(
            "/internal/tasks/analyze-change",
            headers={"Authorization": f"Bearer {TASK_TOKEN}"},
            json={"change_event_id": "other", "source_content": "forbidden"},
        )
        assert malformed.status_code == 422
    assert adapter.fetch_count == 1
    assert adapter.cleanup_count == 1

    async def verify() -> None:
        async with container.unit_of_work_factory() as uow:
            event = await uow.change_events.get(registered.change_event_id)
            jobs = await uow.analysis_jobs.list_for_change(registered.change_event_id)
            risks = await uow.risks.list_for_workspace("vws-1")
        assert event is not None and event.status is ChangeEventStatus.DONE
        assert len(jobs) == 1 and jobs[0].status is AnalysisJobStatus.SUCCEEDED
        assert len(risks) == 1 and risks[0].latest_analysis_job_id == jobs[0].id

    asyncio.run(verify())


def test_retryable_source_failure_is_recorded_then_reclaimed_without_new_task() -> None:
    container, adapter = build_worker(adapter=FakeSourceAdapter(fail_once=True))
    registered = asyncio.run(seed_execution(container, fingerprint="retry"))
    initial_enqueue_attempts = len(container.task_enqueuer.attempts)
    with TestClient(create_worker_app(container)) as client:
        headers = {"Authorization": f"Bearer {TASK_TOKEN}"}
        first = client.post(
            "/internal/tasks/analyze-change",
            headers=headers,
            json={"change_event_id": registered.change_event_id},
        )
        assert first.status_code == 503
        assert first.json()["detail"] == {
            "code": "SOURCE:TEMPORARY_UNAVAILABLE",
            "retryable": True,
        }
        second = client.post(
            "/internal/tasks/analyze-change",
            headers=headers,
            json={"change_event_id": registered.change_event_id},
        )
        assert second.status_code == 200
        assert second.json()["disposition"] == "COMPLETED"
    assert adapter.fetch_count == 2
    assert adapter.cleanup_count == 1
    assert len(container.task_enqueuer.attempts) == initial_enqueue_attempts


def test_missing_analyzer_result_fails_before_cleanup_and_acks() -> None:
    container, adapter = build_worker(
        intelligence=FakeIntelligence(omit_results=True)
    )
    registered = asyncio.run(seed_execution(container, fingerprint="missing-result"))

    async def observe_state_at_cleanup(change: SourceChange):
        async with container.unit_of_work_factory() as uow:
            event = await uow.change_events.get(registered.change_event_id)
            jobs = await uow.analysis_jobs.list_for_change(registered.change_event_id)
        return event.status if event is not None else None, jobs[0].status

    adapter.cleanup_probe = observe_state_at_cleanup
    with TestClient(create_worker_app(container)) as client:
        response = client.post(
            "/internal/tasks/analyze-change",
            headers={"Authorization": f"Bearer {TASK_TOKEN}"},
            json={"change_event_id": registered.change_event_id},
        )
        assert response.status_code == 200
        assert response.json()["disposition"] == "TERMINAL_FAILURE"
        assert response.json()["safe_code"] == "CONTRACT:ANALYZER_RESULT_SET_MISMATCH"
    assert adapter.cleanup_count == 1
    assert adapter.cleanup_observation == (
        ChangeEventStatus.FAILED,
        AnalysisJobStatus.FAILED,
    )

    async def verify() -> None:
        async with container.unit_of_work_factory() as uow:
            event = await uow.change_events.get(registered.change_event_id)
            jobs = await uow.analysis_jobs.list_for_change(registered.change_event_id)
        assert event is not None and event.status is ChangeEventStatus.FAILED
        assert event.last_error_safe == "CONTRACT:ANALYZER_RESULT_SET_MISMATCH"
        assert jobs[0].status is AnalysisJobStatus.FAILED

    asyncio.run(verify())


def test_missing_source_adapter_acks_configuration_failure_and_readiness_fails() -> None:
    complete = CompleteIntelligenceFacade(
        FakeIntelligence(),
        configured_analysis_types=(AnalysisType.PATENT, AnalysisType.LICENSE),
        active_analysis_types=(AnalysisType.PATENT, AnalysisType.LICENSE),
    )
    container = build_container(
        worker_settings(),
        overrides=ContainerOverrides(
            intelligence=complete,
            task_authenticator=StaticBearerTaskAuthenticator(TASK_TOKEN),
        ),
    )
    registered = asyncio.run(seed_execution(container, fingerprint="missing-adapter"))
    with TestClient(create_worker_app(container)) as client:
        readiness = client.get("/health/ready")
        assert readiness.status_code == 503
        assert readiness.json()["checks"]["source_adapters"] == "missing"
        response = client.post(
            "/internal/tasks/analyze-change",
            headers={"Authorization": f"Bearer {TASK_TOKEN}"},
            json={"change_event_id": registered.change_event_id},
        )
        assert response.status_code == 200
        assert response.json()["safe_code"] == "CONFIGURATION:SOURCE_ADAPTER_MISSING"


def test_missing_pipeline_returns_503_instead_of_ack_without_canonical_failure() -> None:
    container = build_container(
        worker_settings(),
        overrides=ContainerOverrides(
            task_authenticator=StaticBearerTaskAuthenticator(TASK_TOKEN),
        ),
    )
    with TestClient(create_worker_app(container)) as client:
        readiness = client.get("/health/ready")
        assert readiness.status_code == 503
        assert readiness.json()["checks"]["analysis_pipeline"] == "missing"
        response = client.post(
            "/internal/tasks/analyze-change",
            headers={"Authorization": f"Bearer {TASK_TOKEN}"},
            json={"change_event_id": "event-without-runtime"},
        )
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "CONFIGURATION:ANALYSIS_PIPELINE_MISSING",
        "retryable": True,
    }
