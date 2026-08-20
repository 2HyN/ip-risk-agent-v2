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
from ip_risk_agent.application.process_change import InMemoryTaskEnqueuer
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
    PublicVwsAction,
    SourceAccessReceiptContext,
    SourceMetadataRegistrationCommand,
)
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import DomainInvariantError
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    MembershipStatus,
    VwsAction,
    membership_id_for,
)
from ip_risk_agent.core.risk import RiskLifecycleState
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def __call__(self) -> datetime:
        return self.current


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, kind: str) -> str:
        self.value += 1
        return f"{kind}-{self.value}"


async def seed_workspace(store: InMemoryControlStore) -> None:
    async with store() as uow:
        await uow.users.add(
            User(
                "owner-1",
                "google-owner-1",
                "owner@example.com",
                "Owner",
                NOW,
                NOW,
            )
        )
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
        await uow.memberships.add(
            Membership(
                membership_id_for("vws-1", "owner-1"),
                "vws-1",
                "owner-1",
                MembershipRole.OWNER,
                MembershipStatus.ACTIVE,
                "owner-1",
                NOW,
                NOW,
            )
        )
        await uow.commit()


def source_command() -> SourceMetadataRegistrationCommand:
    return SourceMetadataRegistrationCommand(
        registration_key="github-installation-1:repo-42:vws-1",
        actor_user_id="owner-1",
        risk_workspace_id="vws-1",
        source_type=SourceType.GITHUB,
        connection_key="github-installation-1",
        source_workspace_key="repo-42",
        external_scope_id="repo-42",
        source_workspace_display_name="example/repository",
        mount_alias="Backend",
        provider_subject="installation-1",
        provider_account_label="example-org",
        credential_ref="secret-ref:github-installation-1",
        tracking_config_safe={"branch": "main", "include": ["src/**"]},
    )


def make_facade(
    store: InMemoryControlStore,
    queue: InMemoryTaskEnqueuer,
    clock: MutableClock,
) -> ControlPlaneFacade:
    return ControlPlaneFacade(
        unit_of_work_factory=store,
        task_enqueuer=queue,
        clock=clock,
        id_factory=SequentialIds(),
        config=ControlPlaneFacadeConfig(
            requested_analysis_types=(AnalysisType.PATENT,)
        ),
    )


def make_change(source) -> SourceChange:
    return SourceChange(
        contract_version="1",
        event_id="source-event-failure",
        provider_event_id="provider-event-failure",
        event_fingerprint="fingerprint-failure",
        risk_workspace_id="vws-1",
        mount_id=source.mount_id,
        source_workspace_id=source.source_workspace_id,
        source_type=SourceType.GITHUB,
        artifact=SourceArtifactRef(
            source_artifact_id="repo:path:src/failure.py",
            display_name="failure.py",
            path_hint="src/failure.py",
        ),
        change_type=ChangeType.CREATE,
        revision="revision-failure",
        observed_at=NOW + timedelta(seconds=1),
        safe_metadata={"branch": "main"},
    )


def test_source_metadata_callbacks_are_authorized_idempotent_and_opaque() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)

        first = await facade.register_source_metadata(source_command())
        second = await facade.register_source_metadata(source_command())
        assert (
            first.connection_id,
            first.source_workspace_id,
            first.mount_id,
        ) == (
            second.connection_id,
            second.source_workspace_id,
            second.mount_id,
        )
        assert first.created_connection and first.created_source_workspace
        assert first.created_mount
        assert not second.created_connection and not second.created_source_workspace
        assert not second.created_mount

        mount_ref = await facade.get_mount_ref(first.mount_id)
        assert mount_ref.risk_workspace_id == "vws-1"
        assert mount_ref.source_type is SourceType.GITHUB
        context = await facade.get_source_workspace_context(first.source_workspace_id)
        assert context.credential_ref == "secret-ref:github-installation-1"
        assert "secret-ref" not in repr(context)

        decision = await facade.authorize_vws_action(
            actor_user_id="owner-1",
            risk_workspace_id="vws-1",
            action=PublicVwsAction.MOUNT_SOURCE_OPERATION,
            mount_id=first.mount_id,
        )
        assert decision.allowed and decision.provider_authority_required
        async with store() as uow:
            audit = await uow.audit.list_for_workspace("vws-1")
        assert [event.event_type.value for event in audit] == [
            "SOURCE_CONNECTED",
            "MOUNT_CREATED",
        ]

    run(scenario())


def test_public_authorization_actions_match_canonical_actions() -> None:
    assert {action.value for action in PublicVwsAction} == {
        action.value for action in VwsAction
    }


def test_facade_runs_source_change_gate_result_and_risk_pipeline() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())

        clock.current = NOW + timedelta(seconds=1)
        change = SourceChange(
            contract_version="1",
            event_id="source-event-1",
            provider_event_id="provider-event-1",
            event_fingerprint="fingerprint-1",
            risk_workspace_id="vws-1",
            mount_id=source.mount_id,
            source_workspace_id=source.source_workspace_id,
            source_type=SourceType.GITHUB,
            artifact=SourceArtifactRef(
                source_artifact_id="repo:path:src/main.py",
                display_name="main.py",
                path_hint="src/main.py",
            ),
            change_type=ChangeType.CREATE,
            revision="revision-1",
            observed_at=clock.current,
            safe_metadata={"branch": "main"},
        )
        registered = await facade.register_source_change(change)
        assert registered.enqueued and registered.analysis_job_id is not None
        assert queue.pending_ids == (registered.change_event_id,)

        clock.current = NOW + timedelta(seconds=2)
        claim = await facade.claim_analysis(registered.change_event_id)
        assert claim is not None and claim.attempt == 1
        receipt = SourceAccessReceipt(
            access_type=SourceAccessType.FULL_CONTENT,
            provider_request_id="provider-request-1",
            content_bytes=23,
            occurred_at=NOW + timedelta(seconds=3),
        )
        access_context = SourceAccessReceiptContext(
            risk_workspace_id="vws-1",
            mount_id=source.mount_id,
            source_workspace_id=source.source_workspace_id,
            source_type=SourceType.GITHUB,
            source_artifact_id="repo:path:src/main.py",
            revision="revision-1",
            receipt=receipt,
            analysis_job_id=claim.analysis_job_id,
        )
        access = await facade.register_source_access(access_context)
        assert access.created
        assert not (await facade.register_source_access(access_context)).created

        snapshot = SourceSnapshot(
            contract_version="1",
            risk_workspace_id="vws-1",
            mount_id=source.mount_id,
            source_workspace_id=source.source_workspace_id,
            source_type=SourceType.GITHUB,
            source_artifact_id="repo:path:src/main.py",
            resolved_revision="revision-1",
            retrieved_at=NOW + timedelta(seconds=3),
            display_name="main.py",
            logical_path_hint="src/main.py",
            mime_type="text/x-python",
            artifact_kind=ArtifactKind.SOURCE_CODE,
            content_scope=ContentScope.FULL_TEXT,
            text_segments=[
                TextSegment(
                    segment_id="segment-1",
                    text="def main(): return True",
                    line_start=1,
                    line_end=1,
                    segment_kind=SegmentKind.CHANGED,
                )
            ],
            checksum="sha256:revision-1",
            byte_size=23,
            source_access_receipt=receipt,
        )
        clock.current = NOW + timedelta(seconds=3)
        built = await facade.build_analysis_artifact(snapshot, claim.analysis_job_id)
        assert built.approved and built.analysis_artifact is not None
        assert built.source_access_event_id == access.source_access_event_id
        assert built.analysis_artifact.security_context.approved

        original = await facade.get_original_source_request(
            actor_user_id="owner-1",
            risk_workspace_id="vws-1",
            artifact_id=registered.artifact_id,
        )
        assert original.provider_authority_required
        assert original.artifact.path_hint is None

        evidence = Evidence(
            evidence_id="evidence-1",
            evidence_type=EvidenceType.PATENT_CLAIM,
            excerpt="A minimal matching claim excerpt.",
            reference="https://example.invalid/patents/1#claim-1",
            metadata_safe={"claim": 1},
        )
        result = AnalysisResult(
            contract_version="1",
            analysis_job_id=claim.analysis_job_id,
            artifact_id=registered.artifact_id,
            revision="revision-1",
            analysis_type=AnalysisType.PATENT,
            status=AnalysisStatus.SUCCEEDED,
            coverage=AnalysisCoverage.COMPLETE,
            candidates=[
                PatentCandidate(
                    normalized_application_number="KR-10-2026-000001",
                    title="Candidate ranking method",
                    suggested_review_priority=ReviewPriority.HIGH,
                    matched_elements=["candidate ranking"],
                    evidence_ids=["evidence-1"],
                    provider_metadata_safe={"jurisdiction": "KR"},
                )
            ],
            evidence=[evidence],
            provider_failures=[],
            versions=AnalysisVersions(analyzer_version="patent-v1"),
            started_at=NOW + timedelta(seconds=2),
            completed_at=NOW + timedelta(seconds=4),
        )
        clock.current = NOW + timedelta(seconds=5)
        accepted = await facade.accept_analysis_result(result)
        assert accepted.disposition == "ACCEPTED"
        assert accepted.job_status == "SUCCEEDED"
        assert accepted.evidence_count == 1
        async with store() as uow:
            risks = await uow.risks.list_for_workspace("vws-1")
        assert len(risks) == 1
        assert risks[0].lifecycle_state is RiskLifecycleState.NEW

    run(scenario())


def test_facade_rejects_sensitive_tracking_metadata() -> None:
    with pytest.raises(DomainInvariantError, match="sensitive key"):
        replace(
            source_command(),
            tracking_config_safe={"access_token": "not-allowed"},
        )


def test_facade_redacts_worker_failure_before_persistence() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        clock.current = NOW + timedelta(seconds=1)
        registration = await facade.register_source_change(make_change(source))
        clock.current = NOW + timedelta(seconds=2)
        assert await facade.claim_analysis(registration.change_event_id) is not None
        clock.current = NOW + timedelta(seconds=3)
        await facade.fail_analysis(
            registration.change_event_id,
            failure_safe="provider failed: Bearer abcdefghijklmnop",
        )
        async with store() as uow:
            event = await uow.change_events.get(registration.change_event_id)
            job = await uow.analysis_jobs.get(registration.analysis_job_id)
        assert event is not None and job is not None
        assert "abcdefghijklmnop" not in (event.last_error_safe or "")
        assert "abcdefghijklmnop" not in (job.failure_safe or "")

    run(scenario())
