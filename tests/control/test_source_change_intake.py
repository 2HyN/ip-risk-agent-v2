from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts import (
    AnalysisType,
    ChangeType,
    ReviewPriority,
    SourceArtifactRef,
    SourceChange,
    SourceType,
)
from ip_risk_agent.application.analysis_jobs import AnalysisJobStatus
from ip_risk_agent.application.analysis_jobs.service import AnalysisJobOrchestrationService
from ip_risk_agent.application.process_change import (
    ChangeEventStatus,
    InMemoryTaskEnqueuer,
    TaskEnqueueError,
)
from ip_risk_agent.application.process_change.service import (
    SourceChangeDisposition,
    SourceChangeIntakeError,
    SourceChangeIntakeService,
)
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.core.artifacts import ArtifactAvailability
from ip_risk_agent.core.common import DomainInvariantError
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 16, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


class AdvancingClock:
    def __init__(self) -> None:
        self.current = NOW

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def make_change(
    *,
    fingerprint: str = "fingerprint-1",
    change_type: ChangeType = ChangeType.CREATE,
    source_artifact_id: str = "repo:path:old.py",
    path_hint: str = "src/old.py",
    revision: str | None = "revision-1",
    previous_revision: str | None = None,
    previous_artifact: SourceArtifactRef | None = None,
) -> SourceChange:
    return SourceChange(
        contract_version="1",
        event_id=f"source-event-{fingerprint}",
        provider_event_id=f"provider-{fingerprint}",
        event_fingerprint=fingerprint,
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        source_workspace_id="source-1",
        source_type=SourceType.GITHUB,
        artifact=SourceArtifactRef(
            source_artifact_id=source_artifact_id,
            display_name=path_hint.rsplit("/", 1)[-1],
            path_hint=path_hint,
        ),
        previous_artifact=previous_artifact,
        change_type=change_type,
        revision=revision,
        previous_revision=previous_revision,
        observed_at=NOW,
        safe_metadata={"repository_id": 42, "tracked_branch": "main"},
    )


async def seed_source_context(
    store: InMemoryControlStore,
    *,
    mount_status: MountStatus = MountStatus.ACTIVE,
    source_status: SourceWorkspaceStatus = SourceWorkspaceStatus.ACTIVE,
    connection_status: SourceConnectionStatus = SourceConnectionStatus.ACTIVE,
) -> None:
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
        await uow.source_metadata.add_connection(
            SourceConnection(
                "connection-1",
                SourceType.GITHUB,
                "manager-1",
                connection_status,
                NOW,
                NOW,
            )
        )
        await uow.source_metadata.add_source_workspace(
            SourceWorkspace(
                "source-1",
                "connection-1",
                SourceType.GITHUB,
                "repo-42",
                "org/repo",
                source_status,
                NOW,
                NOW,
            )
        )
        await uow.mounts.add(
            WorkspaceMount(
                "mount-1",
                "vws-1",
                "source-1",
                "Backend",
                "manager-1",
                "connection-1",
                mount_status,
                NOW,
                NOW,
            )
        )
        await uow.commit()


def make_intake(
    store: InMemoryControlStore,
    queue: InMemoryTaskEnqueuer,
    clock: AdvancingClock | None = None,
) -> SourceChangeIntakeService:
    return SourceChangeIntakeService(
        unit_of_work_factory=store,
        task_enqueuer=queue,
        clock=clock or AdvancingClock(),
    )


def test_create_registers_artifact_event_job_and_raw_free_queue_payload() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(store)
        registration = await make_intake(store, queue).register_source_change(
            make_change()
        )
        assert registration.disposition is SourceChangeDisposition.CREATED
        assert registration.enqueued
        assert queue.pending_ids == (registration.change_event_id,)
        assert queue.attempts == (registration.change_event_id,)

        async with store() as uow:
            event = await uow.change_events.get(registration.change_event_id)
            artifact = await uow.artifacts.get(registration.artifact_id)
            state = await uow.artifacts.get_state(registration.artifact_id)
            jobs = await uow.analysis_jobs.list_for_change(registration.change_event_id)
            assert event is not None and event.status is ChangeEventStatus.PENDING
            assert artifact is not None and artifact.logical_path == "Backend/src/old.py"
            assert state is not None
            assert state.availability_state is ArtifactAvailability.AVAILABLE
            assert len(jobs) == 1 and jobs[0].status is AnalysisJobStatus.QUEUED
            assert jobs[0].requested_analysis_types == (
                AnalysisType.LICENSE,
                AnalysisType.PATENT,
            )

    run(scenario())


def test_duplicate_and_concurrent_delivery_create_one_canonical_record_set() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(store)
        intake = make_intake(store, queue)
        change = make_change()
        first, second = await asyncio.gather(
            intake.register_source_change(change),
            intake.register_source_change(change),
        )
        assert {first.disposition, second.disposition} == {
            SourceChangeDisposition.CREATED,
            SourceChangeDisposition.DUPLICATE_PENDING,
        }
        assert first.change_event_id == second.change_event_id
        assert queue.pending_ids == (first.change_event_id,)
        assert queue.attempts == (first.change_event_id, first.change_event_id)
        async with store() as uow:
            assert len(await uow.analysis_jobs.list_for_change(first.change_event_id)) == 1
            assert await uow.artifacts.get(first.artifact_id) is not None

    run(scenario())


def test_fingerprint_collision_with_different_change_is_rejected() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(store)
        intake = make_intake(store, queue)
        await intake.register_source_change(make_change())
        collision = make_change(
            fingerprint="fingerprint-1",
            source_artifact_id="repo:path:other.py",
            path_hint="src/other.py",
        )
        with pytest.raises(SourceChangeIntakeError, match="reused"):
            await intake.register_source_change(collision)

    run(scenario())


def test_enqueue_failure_leaves_retryable_pending_state() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        queue.fail_next()
        await seed_source_context(store)
        intake = make_intake(store, queue)
        with pytest.raises(TaskEnqueueError):
            await intake.register_source_change(make_change())
        retry = await intake.register_source_change(make_change())
        assert retry.disposition is SourceChangeDisposition.DUPLICATE_PENDING
        assert retry.enqueued
        assert queue.pending_ids == (retry.change_event_id,)

    run(scenario())


def test_failed_duplicate_is_atomically_requeued_and_enqueued_by_intake() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = AdvancingClock()
        await seed_source_context(store)
        intake = make_intake(store, queue, clock)
        registration = await intake.register_source_change(make_change())
        jobs = AnalysisJobOrchestrationService(
            unit_of_work_factory=store,
            task_enqueuer=queue,
            clock=clock,
        )
        assert await jobs.claim(registration.change_event_id) is not None
        await jobs.fail(
            registration.change_event_id,
            failure_safe="provider temporarily unavailable",
        )

        retried = await intake.register_source_change(make_change())
        assert retried.disposition is SourceChangeDisposition.FAILED_REQUEUED
        assert retried.enqueued
        async with store() as uow:
            event = await uow.change_events.get(registration.change_event_id)
            job = (await uow.analysis_jobs.list_for_change(registration.change_event_id))[0]
            assert event is not None and event.status is ChangeEventStatus.PENDING
            assert job.status is AnalysisJobStatus.QUEUED

    run(scenario())


def test_analysis_bearing_change_without_revision_rolls_back_all_staged_records() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(store)
        change = make_change(change_type=ChangeType.UPDATE, revision=None)
        with pytest.raises(DomainInvariantError, match="revision"):
            await make_intake(store, queue).register_source_change(change)
        async with store() as uow:
            assert await uow.change_events.get_by_fingerprint(
                change.event_fingerprint
            ) is None
            assert await uow.artifacts.get_by_source_identity(
                change.source_workspace_id,
                change.artifact.source_artifact_id,
            ) is None
        assert queue.attempts == ()

    run(scenario())


def test_move_requires_previous_artifact_without_partial_writes() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(store)
        change = make_change(change_type=ChangeType.MOVE)
        with pytest.raises(SourceChangeIntakeError, match="previous_artifact"):
            await make_intake(store, queue).register_source_change(change)
        async with store() as uow:
            assert await uow.change_events.get_by_fingerprint(
                change.event_fingerprint
            ) is None
        assert queue.attempts == ()

    run(scenario())


@pytest.mark.parametrize("path_hint", ("/etc/passwd", "C:/secret.txt", "../secret"))
def test_provider_path_must_be_relative_and_traversal_free(path_hint: str) -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(store)
        with pytest.raises(SourceChangeIntakeError, match="provider-relative|traversal"):
            await make_intake(store, queue).register_source_change(
                make_change(path_hint=path_hint)
            )
        assert queue.attempts == ()

    run(scenario())


def test_move_transfers_source_identity_while_preserving_artifact_and_risk_identity() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = AdvancingClock()
        await seed_source_context(store)
        intake = make_intake(store, queue, clock)
        created = await intake.register_source_change(make_change())
        async with store() as uow:
            await uow.risks.add(
                Risk(
                    "risk-1",
                    "vws-1",
                    created.artifact_id,
                    AnalysisType.PATENT,
                    "risk-key-1",
                    RiskLifecycleState.NEW,
                    ReviewDisposition.UNREVIEWED,
                    ReviewPriority.HIGH,
                    "Potential overlap",
                    NOW,
                    NOW,
                    created.analysis_job_id or "job",
                    NOW,
                )
            )
            await uow.commit()

        moved = await intake.register_source_change(
            make_change(
                fingerprint="fingerprint-move",
                change_type=ChangeType.MOVE,
                source_artifact_id="repo:path:new.py",
                path_hint="src/new.py",
                revision="revision-2",
                previous_revision="revision-1",
                previous_artifact=SourceArtifactRef(
                    source_artifact_id="repo:path:old.py",
                    display_name="old.py",
                    path_hint="src/old.py",
                ),
            )
        )
        assert moved.artifact_id == created.artifact_id
        async with store() as uow:
            assert await uow.artifacts.get_by_source_identity(
                "source-1", "repo:path:old.py"
            ) is None
            artifact = await uow.artifacts.get_by_source_identity(
                "source-1", "repo:path:new.py"
            )
            assert artifact is not None and artifact.id == created.artifact_id
            assert artifact.logical_path == "Backend/src/new.py"
            risk = await uow.risks.get("risk-1")
            assert risk is not None and risk.artifact_id == artifact.id

    run(scenario())


def test_move_allows_the_previous_source_identity_to_be_reused_by_a_new_artifact() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = AdvancingClock()
        await seed_source_context(store)
        intake = make_intake(store, queue, clock)
        created = await intake.register_source_change(make_change())
        await intake.register_source_change(
            make_change(
                fingerprint="fingerprint-move",
                change_type=ChangeType.MOVE,
                source_artifact_id="repo:path:new.py",
                path_hint="src/new.py",
                revision="revision-2",
                previous_revision="revision-1",
                previous_artifact=SourceArtifactRef(
                    source_artifact_id="repo:path:old.py",
                    display_name="old.py",
                    path_hint="src/old.py",
                ),
            )
        )
        replacement = await intake.register_source_change(
            make_change(
                fingerprint="fingerprint-reuse-old",
                source_artifact_id="repo:path:old.py",
                path_hint="src/old.py",
                revision="replacement-revision-1",
            )
        )
        assert replacement.artifact_id != created.artifact_id
        async with store() as uow:
            moved = await uow.artifacts.get_by_source_identity(
                "source-1", "repo:path:new.py"
            )
            reused = await uow.artifacts.get_by_source_identity(
                "source-1", "repo:path:old.py"
            )
            assert moved is not None and moved.id == created.artifact_id
            assert reused is not None and reused.id == replacement.artifact_id

    run(scenario())


def test_delete_marks_availability_without_job_or_risk_resolution() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = AdvancingClock()
        await seed_source_context(store)
        intake = make_intake(store, queue, clock)
        created = await intake.register_source_change(make_change())
        async with store() as uow:
            risk = Risk(
                "risk-1",
                "vws-1",
                created.artifact_id,
                AnalysisType.PATENT,
                "risk-key-1",
                RiskLifecycleState.NEW,
                ReviewDisposition.UNREVIEWED,
                ReviewPriority.HIGH,
                "Potential overlap",
                NOW,
                NOW,
                created.analysis_job_id or "job",
                NOW,
            )
            await uow.risks.add(risk)
            await uow.commit()
        before_attempts = queue.attempts

        deleted = await intake.register_source_change(
            make_change(
                fingerprint="fingerprint-delete",
                change_type=ChangeType.DELETE,
                revision=None,
                previous_revision="revision-1",
            )
        )
        assert deleted.disposition is SourceChangeDisposition.DELETE_RECORDED
        assert deleted.analysis_job_id is None and not deleted.enqueued
        assert queue.attempts == before_attempts
        async with store() as uow:
            state = await uow.artifacts.get_state(created.artifact_id)
            event = await uow.change_events.get(deleted.change_event_id)
            risk = await uow.risks.get("risk-1")
            assert state is not None
            assert state.availability_state is ArtifactAvailability.DELETED
            assert event is not None and event.status is ChangeEventStatus.DONE
            assert await uow.analysis_jobs.list_for_change(deleted.change_event_id) == ()
            assert risk is not None and risk.lifecycle_state is RiskLifecycleState.NEW

    run(scenario())


@pytest.mark.parametrize(
    ("mount_status", "source_status", "connection_status"),
    (
        (
            MountStatus.DISABLED,
            SourceWorkspaceStatus.ACTIVE,
            SourceConnectionStatus.ACTIVE,
        ),
        (
            MountStatus.ACTIVE,
            SourceWorkspaceStatus.SOURCE_OFFLINE,
            SourceConnectionStatus.ACTIVE,
        ),
        (
            MountStatus.ACTIVE,
            SourceWorkspaceStatus.ACTIVE,
            SourceConnectionStatus.REAUTH_REQUIRED,
        ),
    ),
)
def test_non_processable_source_context_is_rejected_without_records(
    mount_status, source_status, connection_status
) -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        await seed_source_context(
            store,
            mount_status=mount_status,
            source_status=source_status,
            connection_status=connection_status,
        )
        with pytest.raises(SourceChangeIntakeError, match="not processable|invalid"):
            await make_intake(store, queue).register_source_change(make_change())
        assert queue.attempts == ()

    run(scenario())


def test_job_claim_fail_retry_and_finish_are_idempotent_and_attempt_counted() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = AdvancingClock()
        await seed_source_context(store)
        intake = make_intake(store, queue, clock)
        registration = await intake.register_source_change(make_change())
        jobs = AnalysisJobOrchestrationService(
            unit_of_work_factory=store,
            task_enqueuer=queue,
            clock=clock,
        )
        claimed = await jobs.claim(registration.change_event_id)
        assert claimed is not None
        assert claimed.change_event.attempts == 1
        assert await jobs.claim(registration.change_event_id) is None
        failed = await jobs.fail(
            registration.change_event_id,
            failure_safe="provider temporarily unavailable",
        )
        assert failed.analysis_job.status is AnalysisJobStatus.FAILED
        assert await jobs.fail(
            registration.change_event_id,
            failure_safe="provider temporarily unavailable",
        ) == failed

        attempts_before_retry = len(queue.attempts)
        retried = await jobs.retry_failed(registration.change_event_id)
        assert retried.change_event.status is ChangeEventStatus.PENDING
        assert retried.analysis_job.status is AnalysisJobStatus.QUEUED
        assert len(queue.attempts) == attempts_before_retry + 1
        assert await jobs.retry_failed(registration.change_event_id) == retried
        assert len(queue.attempts) == attempts_before_retry + 2
        claimed_again = await jobs.claim(registration.change_event_id)
        assert claimed_again is not None
        assert claimed_again.change_event.attempts == 2
        finished = await jobs.finish(
            registration.change_event_id,
            status=AnalysisJobStatus.SUCCEEDED,
        )
        assert finished.change_event.status is ChangeEventStatus.DONE
        assert finished.analysis_job.status is AnalysisJobStatus.SUCCEEDED
        assert await jobs.finish(
            registration.change_event_id,
            status=AnalysisJobStatus.SUCCEEDED,
        ) == finished
        queue_attempts = queue.attempts
        duplicate_done = await intake.register_source_change(make_change())
        assert duplicate_done.disposition is SourceChangeDisposition.DUPLICATE_DONE
        assert queue.attempts == queue_attempts

    run(scenario())
