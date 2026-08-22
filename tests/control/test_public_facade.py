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
    SourceHealth,
    SourceHealthStatus,
    SourceSnapshot,
    SourceType,
    TextSegment,
)
from ip_risk_agent.application.process_change import InMemoryTaskEnqueuer
from ip_risk_agent.application.analysis_jobs.service import AnalysisJobOrchestrationError
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
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnectionStatus,
    SourceWorkspaceStatus,
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


def test_provider_reconnection_rotates_the_credential_instead_of_colliding() -> None:
    """같은 계정으로 provider 를 다시 연결하면 Mount 가 계속 만들어져야 한다.

    canonical connection id 는 ``(source_type, provider_subject)`` 에서 파생되므로
    재연결해도 그대로다. 반면 자격증명은 새로 발급되어 ``credential_ref`` 만 바뀐다.
    이것을 registration key collision 으로 거부하면 재연결 이후 어떤 Mount 도
    만들 수 없고, 사용자에게는 mount 요청이 422 로 보인다 — 실제로 그렇게 막혔다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)

        first = await facade.register_source_metadata(source_command())

        rotated = replace(
            source_command(),
            credential_ref="secret-ref:github-installation-1-rotated",
        )
        second = await facade.register_source_metadata(rotated)

        assert second.connection_id == first.connection_id
        assert second.mount_id == first.mount_id
        assert not second.created_connection

        # 옛 참조를 남겨 두면 이후 조회가 폐기된 secret 을 가리킨다.
        context = await facade.get_source_workspace_context(second.source_workspace_id)
        assert context.credential_ref == "secret-ref:github-installation-1-rotated"

    run(scenario())


def test_source_connection_identity_mismatch_is_still_a_collision() -> None:
    """자격증명 회전을 허용해도 정체성 불일치는 계속 거부해야 한다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        await facade.register_source_metadata(source_command())

        for field_name, value in (
            ("actor_user_id", "reviewer-1"),
            ("provider_subject", "installation-2"),
            ("provider_account_label", "other-org"),
        ):
            impostor = replace(source_command(), **{field_name: value})
            try:
                await facade.register_source_metadata(impostor)
            except DomainInvariantError:
                continue
            except PermissionError:
                # actor 가 바뀌면 권한 검사에서 먼저 걸릴 수 있다. 그래도 거부다.
                continue
            raise AssertionError(f"{field_name} mismatch must not be accepted")

    run(scenario())


def test_source_workspace_tracking_scope_grows_without_collision() -> None:
    """추적 범위는 정체성이 아니라 상태다.

    사용자가 같은 source 에 파일을 더 추가하면 tracking 이 정당하게 바뀐다.
    이것을 registration key collision 으로 거부하면 한 번 만든 source workspace 에
    아무것도 더할 수 없다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)

        first = await facade.register_source_metadata(source_command())
        widened = replace(
            source_command(),
            tracking_config_safe={"branch": "main", "include": ["src/**", "docs/**"]},
        )
        second = await facade.register_source_metadata(widened)

        assert second.source_workspace_id == first.source_workspace_id
        assert second.mount_id == first.mount_id
        assert not second.created_source_workspace

        context = await facade.get_source_workspace_context(second.source_workspace_id)
        assert tuple(context.tracking_config_safe["include"]) == ("src/**", "docs/**")

    run(scenario())


def test_public_authorization_actions_match_canonical_actions() -> None:
    assert {action.value for action in PublicVwsAction} == {
        action.value for action in VwsAction
    }


def test_source_health_refresh_converges_canonical_source_status() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        checked_at = NOW + timedelta(minutes=1)

        await facade.record_source_health(
            source.mount_id,
            SourceHealth(
                status=SourceHealthStatus.REAUTH_REQUIRED,
                checked_at=checked_at,
                safe_metadata={},
            ),
        )

        async with store() as uow:
            mount = await uow.mounts.get(source.mount_id)
            workspace = await uow.source_metadata.get_source_workspace(
                source.source_workspace_id
            )
            connection = await uow.source_metadata.get_connection(
                source.connection_id
            )
        assert mount is not None and mount.status is MountStatus.REAUTH_REQUIRED
        assert workspace is not None
        assert workspace.status is SourceWorkspaceStatus.REAUTH_REQUIRED
        assert connection is not None
        assert connection.status is SourceConnectionStatus.REAUTH_REQUIRED

    run(scenario())


def test_claim_preserves_source_change_and_reclaims_without_reenqueue() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        change = make_change(source)
        registered = await facade.register_source_change(change)
        assert len(queue.attempts) == 1

        clock.current = NOW + timedelta(seconds=2)
        first = await facade.claim_analysis(registered.change_event_id)
        assert first is not None
        assert first.source_change == change
        assert first.attempt == 1
        assert first.lease_expires_at == clock.current + timedelta(minutes=5)
        assert await facade.claim_analysis(registered.change_event_id) is None

        clock.current = first.lease_expires_at
        reclaimed = await facade.claim_analysis(registered.change_event_id)
        assert reclaimed is not None and reclaimed.attempt == 2
        assert reclaimed.source_change == change
        assert len(queue.attempts) == 1

        with pytest.raises(AnalysisJobOrchestrationError, match="does not own"):
            await facade.fail_analysis(
                registered.change_event_id,
                failure_safe="stale failure",
                attempt=1,
            )
        await facade.fail_analysis(
            registered.change_event_id,
            failure_safe="retryable provider failure",
            attempt=2,
        )
        with pytest.raises(AnalysisJobOrchestrationError, match="explicit retry"):
            await facade.claim_analysis(registered.change_event_id)
        retried = await facade.claim_analysis(
            registered.change_event_id,
            allow_retry=True,
        )
        assert retried is not None and retried.attempt == 3
        assert len(queue.attempts) == 1

    run(scenario())


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


def test_same_provider_scope_can_mount_into_two_risk_workspaces() -> None:
    """SourceWorkspace 는 mount 를 하나만 가진다(전역 제약).

    따라서 정체성이 VWS 범위가 아니면, 같은 Drive 계정이나 같은 GitHub repository 를
    두 번째 Risk Workspace 에 연결할 때 UniqueConstraintViolation 이 나고 사용자에게는
    mount 요청이 409 로 보인다 — 실제로 새 workspace 에서 그렇게 막혔다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        async with store() as uow:
            await uow.workspaces.add(
                RiskWorkspace(
                    "vws-2", "Second", "owner-1", "security-v1", "retention-v1", NOW, NOW
                )
            )
            await uow.memberships.add(
                Membership(
                    membership_id_for("vws-2", "owner-1"),
                    "vws-2",
                    "owner-1",
                    MembershipRole.OWNER,
                    MembershipStatus.ACTIVE,
                    "owner-1",
                    NOW,
                    NOW,
                )
            )
            await uow.commit()
        facade = make_facade(store, queue, clock)

        first = await facade.register_source_metadata(source_command())
        second = await facade.register_source_metadata(
            replace(
                source_command(),
                risk_workspace_id="vws-2",
                # 조립 계층은 source workspace key 를 VWS 로 한정한다.
                source_workspace_key="vws:vws-2|scope:repo-42",
            )
        )

        assert second.connection_id == first.connection_id
        assert second.source_workspace_id != first.source_workspace_id
        assert second.mount_id != first.mount_id
        assert second.created_mount

    run(scenario())


def test_reconnecting_a_disabled_source_reactivates_the_mount() -> None:
    """소스를 다시 연결하는 것은 "다시 감시하겠다" 는 뜻이다.

    계정 단위 정체성 때문에 재연결은 같은 mount 로 수렴한다. DISABLED 로 남겨 두면
    이후 SourceChange 가 전부 "SourceChange mount is not processable" 로 거부되어
    **한 번 끈 소스를 다시 켤 수 없다** — 운영에서 실제로 그렇게 막혔다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)

        first = await facade.register_source_metadata(source_command())
        async with store() as uow:
            mount = await uow.mounts.get(first.mount_id)
            await uow.mounts.save(
                replace(mount, status=MountStatus.DISABLED, updated_at=NOW)
            )
            await uow.commit()

        second = await facade.register_source_metadata(source_command())
        assert second.mount_id == first.mount_id
        assert not second.created_mount

        async with store() as uow:
            revived = await uow.mounts.get(first.mount_id)
        assert revived.status is MountStatus.ACTIVE

    run(scenario())


def test_reanalysis_reruns_a_finished_analysis() -> None:
    """파일 변경 없이 다시 검사할 수 있어야 한다.

    `retry_failed_analysis` 는 FAILED 만 되돌린다. 재검사의 요점은 이미 끝난
    결과도 다시 돌리는 것이다 — 재현을 파일 재업로드에 의존하면 디버깅과 검증이
    모두 느려진다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        receipt = await facade.register_source_change(make_change(source))

        claim = await facade.claim_analysis(receipt.change_event_id)
        assert claim is not None
        await facade.fail_analysis(
            receipt.change_event_id, failure_safe="CONTRACT:X", attempt=claim.attempt
        )

        before = len(queue.attempts)
        await facade.request_reanalysis(receipt.change_event_id)
        assert len(queue.attempts) == before + 1

        # 되돌린 뒤에는 다시 점유할 수 있어야 한다.
        again = await facade.claim_analysis(receipt.change_event_id)
        assert again is not None
        assert again.attempt > claim.attempt

    run(scenario())


def test_reanalysis_refuses_an_in_flight_analysis() -> None:
    """진행 중인 실행을 되돌리면 늦게 도착한 결과가 새 시도를 덮는다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        receipt = await facade.register_source_change(make_change(source))

        claim = await facade.claim_analysis(receipt.change_event_id)
        assert claim is not None  # 이제 PROCESSING/RUNNING 이다

        with pytest.raises(DomainInvariantError):
            await facade.request_reanalysis(receipt.change_event_id)

    run(scenario())


def test_reanalysis_authorization_requires_the_mount() -> None:
    """`MOUNT_SOURCE_OPERATION` 은 mount 단위 권한이다.

    mount 를 넘기지 않으면 workspace 소유자여도 `MOUNT_REQUIRED` 로 거부된다.
    운영에서 "다시 검사" 가 Permission denied 로 막힌 원인이 이것이었다.
    """
    from ip_risk_agent.core.memberships import (
        AuthorizationReason,
        VwsAction,
        authorize_vws_action,
    )

    membership = Membership(
        membership_id_for("vws-1", "owner-1"),
        "vws-1",
        "owner-1",
        MembershipRole.OWNER,
        MembershipStatus.ACTIVE,
        "owner-1",
        NOW,
        NOW,
    )
    without_mount = authorize_vws_action(
        actor_user_id="owner-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_SOURCE_OPERATION,
    )
    assert not without_mount.allowed
    assert without_mount.reason is AuthorizationReason.MOUNT_REQUIRED


def test_reanalysis_is_authorized_for_the_mount_custodian() -> None:
    """재분석은 provider 를 다시 호출하므로 mount 소유 검사가 올바른 경계다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())

        async with store() as uow:
            mount = await uow.mounts.get(source.mount_id)

        from ip_risk_agent.core.memberships import VwsAction, authorize_vws_action

        async with store() as uow:
            membership = await uow.memberships.get("vws-1", "owner-1")
        decision = authorize_vws_action(
            actor_user_id="owner-1",
            risk_workspace_id="vws-1",
            membership=membership,
            action=VwsAction.MOUNT_SOURCE_OPERATION,
            mount=mount,
        )
        assert decision.allowed
        assert decision.provider_authority_required

    run(scenario())


def test_security_service_reanalysis_passes_authorization_end_to_end() -> None:
    """라우트가 실제로 쓰는 경로를 통과시킨다.

    앞선 구현은 mount 를 넘기지 않아 배포에서 Permission denied 로 막혔고, 단위
    테스트만으로는 그것을 잡지 못했다.
    """

    async def scenario() -> None:
        from ip_risk_agent.application.security_policy.service import (
            WorkspaceSecurityService,
        )

        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        receipt = await facade.register_source_change(make_change(source))
        claim = await facade.claim_analysis(receipt.change_event_id)
        assert claim is not None
        await facade.fail_analysis(
            receipt.change_event_id, failure_safe="CONTRACT:X", attempt=claim.attempt
        )

        security = WorkspaceSecurityService(
            unit_of_work_factory=store,
            clock=clock,
            id_factory=SequentialIds(),
            reanalysis_requester=facade.request_reanalysis,
        )
        before = len(queue.attempts)
        await security.request_reanalysis(
            risk_workspace_id="vws-1",
            actor_user_id="owner-1",
            change_event_id=receipt.change_event_id,
        )
        assert len(queue.attempts) == before + 1

    run(scenario())


def test_security_service_reanalysis_rejects_another_workspace() -> None:
    """id 만 알면 남의 workspace 를 돌릴 수 있으면 안 된다."""

    async def scenario() -> None:
        from ip_risk_agent.application.repositories import RecordNotFoundError
        from ip_risk_agent.application.security_policy.service import (
            WorkspaceSecurityService,
        )

        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        async with store() as uow:
            await uow.workspaces.add(
                RiskWorkspace(
                    "vws-2", "Other", "owner-1", "security-v1", "retention-v1", NOW, NOW
                )
            )
            await uow.memberships.add(
                Membership(
                    membership_id_for("vws-2", "owner-1"),
                    "vws-2",
                    "owner-1",
                    MembershipRole.OWNER,
                    MembershipStatus.ACTIVE,
                    "owner-1",
                    NOW,
                    NOW,
                )
            )
            await uow.commit()
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        receipt = await facade.register_source_change(make_change(source))

        security = WorkspaceSecurityService(
            unit_of_work_factory=store,
            clock=clock,
            id_factory=SequentialIds(),
            reanalysis_requester=facade.request_reanalysis,
        )
        with pytest.raises(RecordNotFoundError):
            await security.request_reanalysis(
                risk_workspace_id="vws-2",
                actor_user_id="owner-1",
                change_event_id=receipt.change_event_id,
            )

    run(scenario())


def test_reanalysis_reruns_an_analysis_that_already_succeeded() -> None:
    """재검사의 본래 대상은 **성공한** 분석이다.

    저장소 불변조건이 이전 상태를 FAILED/RUNNING 으로만 허용해서, 성공한 분석에
    "다시 검사" 를 누르면 "analysis job outcomes are append-only within an attempt"
    로 막혔다. 기존 시험이 전부 실패한 분석만 다시 돌려서 드러나지 않았다.

    이 불변조건이 막으려는 것은 한 attempt 안에서 판정이 조용히 바뀌는 것이지,
    새 attempt 를 여는 것이 아니다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        await seed_workspace(store)
        facade = make_facade(store, queue, clock)
        source = await facade.register_source_metadata(source_command())
        receipt = await facade.register_source_change(make_change(source))
        claim = await facade.claim_analysis(receipt.change_event_id)
        assert claim is not None

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
            artifact_id=receipt.artifact_id,
            revision="revision-failure",
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
        assert accepted.job_status == "SUCCEEDED"

        before = len(queue.attempts)
        clock.current = NOW + timedelta(seconds=6)
        await facade.request_reanalysis(receipt.change_event_id)
        assert len(queue.attempts) == before + 1

        again = await facade.claim_analysis(receipt.change_event_id)
        assert again is not None
        assert again.attempt > claim.attempt
        # 이전 판정은 지워져야 한다. 남으면 새 결과가 "이미 있는 결과" 로 취급된다.
        async with store() as uow:
            job = await uow.analysis_jobs.get(claim.analysis_job_id)
        assert job.analysis_outcomes == {}

    run(scenario())
