"""Idempotent SourceChange intake and canonical Artifact/Job orchestration."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath

from iprisk_contracts import AnalysisType, ChangeType, SourceChange
from ip_risk_agent.application.analysis_jobs.models import (
    AnalysisJob,
    AnalysisJobStatus,
    analysis_job_id_for,
)
from ip_risk_agent.application.analysis_jobs.transitions import requeue_analysis_job
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
)
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
    artifact_id_for,
)
from ip_risk_agent.core.common import (
    DomainInvariantError,
    normalize_utc,
    require_non_empty,
    stable_key,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnectionStatus,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.workspaces import RiskWorkspaceStatus

from ip_risk_agent.application.risk_exclusion import (
    exclude_artifact_risks,
    revive_artifact_risks,
)

from .models import ChangeEvent, ChangeEventStatus, change_event_id_for
from .queue import TaskEnqueuer
from .transitions import requeue_change_event

Clock = Callable[[], datetime]


def _random_id(kind: str) -> str:
    """이력 ID 기본 생성기.

    composition 의 ``opaque_id`` 와 같은 모양이지만 여기서 만든다 — application 층이
    composition 을 끌어오면 층이 뒤집힌다 (§3). 배포는 컨테이너가 넘겨 준다.
    """
    normalized = kind.strip().replace("_", "-")
    if not normalized:
        raise ValueError("id kind must not be empty")
    return f"{normalized}-{secrets.token_urlsafe(24)}"


class SourceChangeDisposition(StrEnum):
    CREATED = "CREATED"
    DELETE_RECORDED = "DELETE_RECORDED"
    DUPLICATE_PENDING = "DUPLICATE_PENDING"
    DUPLICATE_PROCESSING = "DUPLICATE_PROCESSING"
    DUPLICATE_DONE = "DUPLICATE_DONE"
    DUPLICATE_FAILED = "DUPLICATE_FAILED"
    FAILED_REQUEUED = "FAILED_REQUEUED"


class SourceChangeIntakeError(DomainInvariantError):
    """이 예외의 메시지는 모두 개발자가 쓴 상수다.

    그래서 진단 로그에 사유를 노출해도 사용자 데이터나 provider 페이로드가 새지
    않는다. 클래스 이름만 남기면 어떤 불변조건이 깨졌는지 알 수 없어 배포에서
    원인을 좁힐 수 없었다.
    """


@dataclass(frozen=True, slots=True)
class SourceChangeRegistration:
    change_event_id: str
    artifact_id: str
    analysis_job_id: str | None
    disposition: SourceChangeDisposition
    enqueued: bool


@dataclass(frozen=True, slots=True)
class _PersistenceOutcome:
    registration: SourceChangeRegistration
    should_enqueue: bool


class SourceChangeIntakeService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        task_enqueuer: TaskEnqueuer,
        clock: Clock,
        requested_analysis_types: tuple[AnalysisType, ...] = (
            AnalysisType.PATENT,
            AnalysisType.LICENSE,
        ),
        retry_failed_events: bool = True,
        concurrency_attempts: int = 3,
        id_factory: Callable[[str], str] = _random_id,
    ) -> None:
        requested = tuple(sorted(set(requested_analysis_types), key=lambda item: item.value))
        if not requested:
            raise ValueError("requested_analysis_types must not be empty")
        if concurrency_attempts < 1:
            raise ValueError("concurrency_attempts must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._id_factory = id_factory
        self._task_enqueuer = task_enqueuer
        self._clock = clock
        self._requested_analysis_types = requested
        self._retry_failed_events = retry_failed_events
        self._concurrency_attempts = concurrency_attempts

    async def register_source_change(
        self, change: SourceChange
    ) -> SourceChangeRegistration:
        last_conflict: ConcurrencyConflictError | None = None
        for _ in range(self._concurrency_attempts):
            try:
                outcome = await self._persist(change)
                break
            except ConcurrencyConflictError as exc:
                last_conflict = exc
        else:
            assert last_conflict is not None
            raise last_conflict

        if outcome.should_enqueue:
            await self._task_enqueuer.enqueue_change(
                outcome.registration.change_event_id
            )
            return replace(outcome.registration, enqueued=True)
        return outcome.registration

    async def _persist(self, change: SourceChange) -> _PersistenceOutcome:
        async with self._unit_of_work_factory() as uow:
            existing = await uow.change_events.get_by_fingerprint(
                change.event_fingerprint
            )
            if existing is not None:
                return await self._handle_duplicate(uow, existing, change)

            mount = await _require_source_context(uow, change)
            occurred_at = normalize_utc(self._clock(), "source_change_intake.clock")
            previously_unavailable = await _was_unavailable(uow, change)
            artifact, state, is_new = await _apply_artifact_change(
                uow,
                change=change,
                mount=mount,
                occurred_at=occurred_at,
            )
            is_delete = change.change_type is ChangeType.DELETE

            if is_delete:
                # 추적이 끝난 파일의 Risk 를 아무도 닫지 않았다. 해소는 분석 결과
                # 수용에서만 일어나는데 DELETE 는 분석 작업을 만들지 않는다. 파일은
                # 없는데 Risk 만 목록에 남았다 (§7.1).
                #
                # 삭제 · 폴더 이탈 · 접근 상실이 모두 여기로 들어온다. 피드에서 셋이
                # 같은 모양으로 오고, 추적 조건이 "공유받은 폴더 안에 있는 것" 하나라
                # 깨지는 방법을 가릴 이유가 없다.
                await exclude_artifact_risks(
                    uow,
                    risk_workspace_id=change.risk_workspace_id,
                    artifact_id=artifact.id,
                    occurred_at=occurred_at,
                    reason_safe="SOURCE_ARTIFACT_UNTRACKED",
                    id_factory=self._id_factory,
                )
            elif previously_unavailable:
                # 파일이 돌아왔다. 분석을 기다리면 안 된다 — 판본이 그대로면 변경
                # 지문이 겹쳐 중복으로 처리되고 분석이 아예 돌지 않는다. 잠깐 옮겼다
                # 되돌리는 흔한 일이 정확히 그 경우다 (§7.1).
                await revive_artifact_risks(
                    uow,
                    risk_workspace_id=change.risk_workspace_id,
                    artifact_id=artifact.id,
                    revision=change.revision,
                    occurred_at=occurred_at,
                    reason_safe="SOURCE_ARTIFACT_TRACKED_AGAIN",
                    id_factory=self._id_factory,
                )
            event = ChangeEvent(
                id=change_event_id_for(change.event_fingerprint),
                event_fingerprint=change.event_fingerprint,
                risk_workspace_id=change.risk_workspace_id,
                mount_id=change.mount_id,
                source_workspace_id=change.source_workspace_id,
                source_artifact_id=change.artifact.source_artifact_id,
                source_type=change.source_type,
                change_type=change.change_type,
                revision=change.revision,
                previous_revision=change.previous_revision,
                observed_at=change.observed_at,
                source_change=change,
                status=ChangeEventStatus.DONE if is_delete else ChangeEventStatus.PENDING,
                attempts=0,
                created_at=occurred_at,
                updated_at=occurred_at,
                artifact_id=artifact.id,
                provider_event_id=change.provider_event_id,
                safe_metadata=change.safe_metadata,
            )
            if is_new:
                await uow.artifacts.add(artifact, state)
            else:
                await uow.artifacts.save(artifact)
                await uow.artifacts.save_state(state)
            await uow.change_events.add(event)

            job = None
            if not is_delete:
                revision = require_non_empty(
                    change.revision or "", "source_change.revision"
                )
                job = AnalysisJob(
                    id=analysis_job_id_for(event.id),
                    change_event_id=event.id,
                    artifact_id=artifact.id,
                    revision=revision,
                    requested_analysis_types=self._requested_analysis_types,
                    status=AnalysisJobStatus.QUEUED,
                    created_at=occurred_at,
                )
                await uow.analysis_jobs.add(job)
            await uow.commit()

        return _PersistenceOutcome(
            SourceChangeRegistration(
                change_event_id=event.id,
                artifact_id=artifact.id,
                analysis_job_id=None if job is None else job.id,
                disposition=(
                    SourceChangeDisposition.DELETE_RECORDED
                    if is_delete
                    else SourceChangeDisposition.CREATED
                ),
                enqueued=False,
            ),
            should_enqueue=not is_delete,
        )

    async def _handle_duplicate(
        self,
        uow: ControlUnitOfWork,
        existing: ChangeEvent,
        change: SourceChange,
    ) -> _PersistenceOutcome:
        _require_matching_duplicate(existing, change)
        if existing.artifact_id is None:
            raise SourceChangeIntakeError("persisted ChangeEvent is missing artifact_id")
        jobs = await uow.analysis_jobs.list_for_change(existing.id)
        if existing.change_type is ChangeType.DELETE:
            if existing.status is not ChangeEventStatus.DONE:
                raise SourceChangeIntakeError("DELETE ChangeEvent must be DONE")
            if jobs:
                raise SourceChangeIntakeError("DELETE ChangeEvent cannot have AnalysisJob")
            return _duplicate_outcome(
                existing,
                None,
                SourceChangeDisposition.DUPLICATE_DONE,
                should_enqueue=False,
            )
        if len(jobs) != 1:
            raise SourceChangeIntakeError(
                "analysis-bearing ChangeEvent must have exactly one AnalysisJob"
            )
        job = jobs[0]
        if job.artifact_id != existing.artifact_id:
            raise SourceChangeIntakeError("AnalysisJob artifact does not match ChangeEvent")
        if existing.status is ChangeEventStatus.PENDING:
            if job.status is not AnalysisJobStatus.QUEUED:
                raise SourceChangeIntakeError("PENDING ChangeEvent requires QUEUED AnalysisJob")
            return _duplicate_outcome(
                existing,
                job,
                SourceChangeDisposition.DUPLICATE_PENDING,
                should_enqueue=True,
            )
        if existing.status is ChangeEventStatus.PROCESSING:
            if job.status is not AnalysisJobStatus.RUNNING:
                raise SourceChangeIntakeError(
                    "PROCESSING ChangeEvent requires RUNNING AnalysisJob"
                )
            return _duplicate_outcome(
                existing,
                job,
                SourceChangeDisposition.DUPLICATE_PROCESSING,
                should_enqueue=False,
            )
        if existing.status is ChangeEventStatus.DONE:
            if job.status not in {
                AnalysisJobStatus.SUCCEEDED,
                AnalysisJobStatus.INCONCLUSIVE,
            }:
                raise SourceChangeIntakeError(
                    "DONE ChangeEvent requires a completed AnalysisJob"
                )
            return _duplicate_outcome(
                existing,
                job,
                SourceChangeDisposition.DUPLICATE_DONE,
                should_enqueue=False,
            )
        if job.status is not AnalysisJobStatus.FAILED:
            raise SourceChangeIntakeError("FAILED ChangeEvent requires FAILED AnalysisJob")
        if not self._retry_failed_events:
            return _duplicate_outcome(
                existing,
                job,
                SourceChangeDisposition.DUPLICATE_FAILED,
                should_enqueue=False,
            )
        occurred_at = normalize_utc(self._clock(), "source_change_retry.clock")
        event = requeue_change_event(existing, occurred_at=occurred_at)
        job = requeue_analysis_job(job)
        await uow.change_events.save(event)
        await uow.analysis_jobs.save(job)
        await uow.commit()
        return _duplicate_outcome(
            event,
            job,
            SourceChangeDisposition.FAILED_REQUEUED,
            should_enqueue=True,
        )


async def _require_source_context(
    uow: ControlUnitOfWork, change: SourceChange
) -> WorkspaceMount:
    workspace = await uow.workspaces.get(change.risk_workspace_id)
    if workspace is None or workspace.status is not RiskWorkspaceStatus.ACTIVE:
        raise SourceChangeIntakeError("SourceChange workspace is unavailable")
    mount = await uow.mounts.get(change.mount_id)
    if mount is None:
        raise SourceChangeIntakeError("SourceChange mount was not found")
    if (
        mount.risk_workspace_id != change.risk_workspace_id
        or mount.source_workspace_id != change.source_workspace_id
    ):
        raise SourceChangeIntakeError("SourceChange does not match Mount scope")
    if mount.status is not MountStatus.ACTIVE:
        raise SourceChangeIntakeError("SourceChange mount is not processable")
    source_workspace = await uow.source_metadata.get_source_workspace(
        change.source_workspace_id
    )
    if source_workspace is None:
        raise SourceChangeIntakeError("SourceChange source workspace was not found")
    if (
        source_workspace.source_connection_id != mount.source_connection_id
        or source_workspace.source_type is not change.source_type
        or source_workspace.status is not SourceWorkspaceStatus.ACTIVE
    ):
        raise SourceChangeIntakeError("SourceChange source workspace context is invalid")
    connection = await uow.source_metadata.get_connection(mount.source_connection_id)
    if connection is None:
        raise SourceChangeIntakeError("SourceChange source connection was not found")
    if (
        connection.provider is not change.source_type
        or connection.status is not SourceConnectionStatus.ACTIVE
    ):
        raise SourceChangeIntakeError("SourceChange source connection is not processable")
    return mount


async def _apply_artifact_change(
    uow: ControlUnitOfWork,
    *,
    change: SourceChange,
    mount: WorkspaceMount,
    occurred_at: datetime,
) -> tuple[Artifact, ArtifactState, bool]:
    current_ref = change.artifact
    existing = None
    if change.change_type is ChangeType.MOVE:
        if change.previous_artifact is None:
            raise SourceChangeIntakeError("MOVE requires previous_artifact")
        existing = await uow.artifacts.get_by_source_identity(
            change.source_workspace_id,
            change.previous_artifact.source_artifact_id,
        )
        if existing is None:
            raise SourceChangeIntakeError("MOVE previous Artifact was not found")
    else:
        if change.previous_artifact is not None:
            raise SourceChangeIntakeError("previous_artifact is only valid for MOVE")
        existing = await uow.artifacts.get_by_source_identity(
            change.source_workspace_id,
            current_ref.source_artifact_id,
        )

    logical_path = _logical_path(mount.alias, current_ref.path_hint, current_ref.display_name)
    availability = (
        ArtifactAvailability.DELETED
        if change.change_type is ChangeType.DELETE
        else ArtifactAvailability.AVAILABLE
    )
    if existing is None:
        artifact_id = artifact_id_for(
            change.source_workspace_id, current_ref.source_artifact_id
        )
        id_owner = await uow.artifacts.get(artifact_id)
        if id_owner is not None:
            artifact_id = stable_key(
                "artifact-instance",
                (
                    change.source_workspace_id,
                    current_ref.source_artifact_id,
                    change.event_fingerprint,
                ),
            )
        artifact = Artifact(
            id=artifact_id,
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=change.source_type,
            source_artifact_id=current_ref.source_artifact_id,
            display_name=current_ref.display_name,
            logical_path=logical_path,
            status=ArtifactStatus.ACTIVE,
            first_seen_at=occurred_at,
            last_seen_at=occurred_at,
        )
        state = ArtifactState(
            artifact_id=artifact.id,
            latest_revision=change.revision or change.previous_revision,
            latest_checksum=None,
            availability_state=availability,
            updated_at=occurred_at,
        )
        return artifact, state, True

    state = await uow.artifacts.get_state(existing.id)
    if state is None:
        raise SourceChangeIntakeError("Artifact is missing canonical ArtifactState")
    effective_time = max(occurred_at, existing.last_seen_at, state.updated_at)
    artifact = replace(
        existing,
        risk_workspace_id=change.risk_workspace_id,
        mount_id=change.mount_id,
        source_workspace_id=change.source_workspace_id,
        source_type=change.source_type,
        source_artifact_id=current_ref.source_artifact_id,
        display_name=current_ref.display_name,
        logical_path=logical_path,
        status=ArtifactStatus.ACTIVE,
        last_seen_at=effective_time,
    )
    state = replace(
        state,
        latest_revision=(
            change.revision
            if change.revision is not None
            else state.latest_revision
        ),
        latest_checksum=None,
        availability_state=availability,
        updated_at=effective_time,
    )
    return artifact, state, False


def _logical_path(alias: str, path_hint: str | None, display_name: str) -> str:
    relative = require_non_empty(path_hint or display_name, "source_artifact.path_hint")
    if "\\" in relative or relative.startswith("/") or re.match(r"^[A-Za-z]:", relative):
        raise SourceChangeIntakeError("source artifact path must be provider-relative")
    path = PurePosixPath(relative)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SourceChangeIntakeError("source artifact path contains invalid traversal")
    return f"{alias}/{'/'.join(path.parts)}"


def _require_matching_duplicate(existing: ChangeEvent, change: SourceChange) -> None:
    expected = (
        existing.risk_workspace_id,
        existing.mount_id,
        existing.source_workspace_id,
        existing.source_type,
        existing.source_artifact_id,
        existing.change_type,
        existing.revision,
        existing.previous_revision,
        existing.provider_event_id,
    )
    received = (
        change.risk_workspace_id,
        change.mount_id,
        change.source_workspace_id,
        change.source_type,
        change.artifact.source_artifact_id,
        change.change_type,
        change.revision,
        change.previous_revision,
        change.provider_event_id,
    )
    if expected != received:
        raise SourceChangeIntakeError(
            "event_fingerprint was reused for a different SourceChange"
        )


def _duplicate_outcome(
    event: ChangeEvent,
    job: AnalysisJob | None,
    disposition: SourceChangeDisposition,
    *,
    should_enqueue: bool,
) -> _PersistenceOutcome:
    assert event.artifact_id is not None
    return _PersistenceOutcome(
        SourceChangeRegistration(
            change_event_id=event.id,
            artifact_id=event.artifact_id,
            analysis_job_id=None if job is None else job.id,
            disposition=disposition,
            enqueued=False,
        ),
        should_enqueue=should_enqueue,
    )


__all__ = [
    "SourceChangeDisposition",
    "SourceChangeIntakeError",
    "SourceChangeIntakeService",
    "SourceChangeRegistration",
]


async def _was_unavailable(uow: ControlUnitOfWork, change: SourceChange) -> bool:
    """이 파일이 방금 전까지 추적 밖이었는가.

    ``_apply_artifact_change`` 가 상태를 덮기 **전에** 물어야 한다. 덮고 나면 항상
    ``AVAILABLE`` 이라 되살아난 것인지 원래 있던 것인지 알 수 없다.
    """
    reference = change.artifact
    if change.change_type is ChangeType.MOVE and change.previous_artifact is not None:
        reference = change.previous_artifact
    existing = await uow.artifacts.get_by_source_identity(
        change.source_workspace_id, reference.source_artifact_id
    )
    if existing is None:
        return False
    state = await uow.artifacts.get_state(existing.id)
    return state is not None and state.availability_state is not ArtifactAvailability.AVAILABLE
