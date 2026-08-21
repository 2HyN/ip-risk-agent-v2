"""Transactional claim/finish/fail orchestration for one ChangeEvent job."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.common import DomainInvariantError, normalize_utc

from ip_risk_agent.application.process_change.models import (
    ChangeEvent,
    ChangeEventStatus,
)
from ip_risk_agent.application.process_change.queue import TaskEnqueuer
from ip_risk_agent.application.process_change.transitions import (
    reanalyze_change_event,
    claim_change_event,
    complete_change_event,
    fail_change_event,
    reclaim_change_event,
    requeue_change_event,
)

from .models import AnalysisJob, AnalysisJobStatus

from .transitions import (
    reanalyze_analysis_job,
    claim_analysis_job,
    complete_analysis_job,
    reclaim_analysis_job,
    requeue_analysis_job,
)

Clock = Callable[[], datetime]


class AnalysisJobOrchestrationError(DomainInvariantError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisExecutionState:
    change_event: ChangeEvent
    analysis_job: AnalysisJob


class AnalysisJobOrchestrationService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        task_enqueuer: TaskEnqueuer,
        clock: Clock,
        lease_duration: timedelta = timedelta(minutes=5),
        concurrency_attempts: int = 3,
    ) -> None:
        if concurrency_attempts < 1:
            raise ValueError("concurrency_attempts must be positive")
        if lease_duration <= timedelta(0) or lease_duration > timedelta(hours=1):
            raise ValueError("lease_duration must be between 0 and 1 hour")
        self._unit_of_work_factory = unit_of_work_factory
        self._task_enqueuer = task_enqueuer
        self._clock = clock
        self._lease_duration = lease_duration
        self._concurrency_attempts = concurrency_attempts

    async def claim(
        self,
        change_event_id: str,
        *,
        allow_retry: bool = False,
    ) -> AnalysisExecutionState | None:
        last_conflict: ConcurrencyConflictError | None = None
        for _ in range(self._concurrency_attempts):
            try:
                return await self._claim_once(
                    change_event_id,
                    allow_retry=allow_retry,
                )
            except ConcurrencyConflictError as exc:
                last_conflict = exc
        assert last_conflict is not None
        raise last_conflict

    async def _claim_once(
        self,
        change_event_id: str,
        *,
        allow_retry: bool,
    ) -> AnalysisExecutionState | None:
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
            occurred_at = normalize_utc(self._clock(), "analysis_claim.clock")
            if (
                event.status is ChangeEventStatus.PROCESSING
                and job.status is AnalysisJobStatus.RUNNING
            ):
                if (
                    event.lease_expires_at is not None
                    and event.lease_expires_at > occurred_at
                ):
                    return None
                event = reclaim_change_event(
                    event,
                    occurred_at=occurred_at,
                    lease_expires_at=occurred_at + self._lease_duration,
                )
                job = reclaim_analysis_job(job, occurred_at=occurred_at)
            elif (
                event.status is ChangeEventStatus.FAILED
                and job.status is AnalysisJobStatus.FAILED
            ):
                if not allow_retry:
                    raise AnalysisJobOrchestrationError(
                        "failed execution requires an explicit retry claim"
                    )
                event = reclaim_change_event(
                    event,
                    occurred_at=occurred_at,
                    lease_expires_at=occurred_at + self._lease_duration,
                )
                job = reclaim_analysis_job(job, occurred_at=occurred_at)
            elif event.status is ChangeEventStatus.DONE and job.status in {
                AnalysisJobStatus.SUCCEEDED,
                AnalysisJobStatus.INCONCLUSIVE,
            }:
                return None
            elif event.status is ChangeEventStatus.PENDING:
                if job.status is not AnalysisJobStatus.QUEUED:
                    raise AnalysisJobOrchestrationError(
                        "PENDING ChangeEvent requires QUEUED AnalysisJob"
                    )
                event = claim_change_event(
                    event,
                    occurred_at=occurred_at,
                    lease_expires_at=occurred_at + self._lease_duration,
                )
                job = claim_analysis_job(job, occurred_at=occurred_at)
            else:
                raise AnalysisJobOrchestrationError(
                    "execution state cannot be claimed"
                )
            await uow.change_events.save(event)
            await uow.analysis_jobs.save(job)
            await uow.commit()
        return AnalysisExecutionState(event, job)

    async def finish(
        self,
        change_event_id: str,
        *,
        status: AnalysisJobStatus,
        failure_safe: str | None = None,
    ) -> AnalysisExecutionState:
        if status not in {
            AnalysisJobStatus.SUCCEEDED,
            AnalysisJobStatus.INCONCLUSIVE,
        }:
            raise AnalysisJobOrchestrationError(
                "finish status must be SUCCEEDED or INCONCLUSIVE"
            )
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
            if event.status is ChangeEventStatus.DONE and job.status is status:
                return AnalysisExecutionState(event, job)
            if (
                event.status is not ChangeEventStatus.PROCESSING
                or job.status is not AnalysisJobStatus.RUNNING
            ):
                raise AnalysisJobOrchestrationError(
                    "only a running execution may finish"
                )
            occurred_at = self._clock()
            job = complete_analysis_job(
                job,
                status=status,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            )
            event = complete_change_event(event, occurred_at=occurred_at)
            await uow.analysis_jobs.save(job)
            await uow.change_events.save(event)
            await uow.commit()
        return AnalysisExecutionState(event, job)

    async def fail(
        self,
        change_event_id: str,
        *,
        failure_safe: str,
        attempt: int | None = None,
    ) -> AnalysisExecutionState:
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
            if attempt is not None and event.attempts != attempt:
                raise AnalysisJobOrchestrationError(
                    "analysis failure attempt does not own the current lease"
                )
            if (
                event.status is ChangeEventStatus.FAILED
                and job.status is AnalysisJobStatus.FAILED
                and event.last_error_safe == failure_safe.strip()
                and job.failure_safe == failure_safe.strip()
            ):
                return AnalysisExecutionState(event, job)
            if (
                event.status is not ChangeEventStatus.PROCESSING
                or job.status is not AnalysisJobStatus.RUNNING
            ):
                raise AnalysisJobOrchestrationError(
                    "only a running execution may fail"
                )
            occurred_at = self._clock()
            job = complete_analysis_job(
                job,
                status=AnalysisJobStatus.FAILED,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            )
            event = fail_change_event(
                event,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            )
            await uow.analysis_jobs.save(job)
            await uow.change_events.save(event)
            await uow.commit()
        return AnalysisExecutionState(event, job)

    async def request_reanalysis(self, change_event_id: str) -> AnalysisExecutionState:
        """변경 없이 같은 artifact 를 다시 검사한다.

        `retry_failed` 는 FAILED 만 되돌린다. 재검사는 이미 끝난 결과도 다시 돌려야
        하고, 그것이 이 기능의 요점이다. 진행 중이면 거부한다.
        """
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
            event = reanalyze_change_event(event, occurred_at=self._clock())
            job = reanalyze_analysis_job(job)
            await uow.change_events.save(event)
            await uow.analysis_jobs.save(job)
            await uow.commit()
            state = AnalysisExecutionState(event, job)
        await self._task_enqueuer.enqueue_change(change_event_id)
        return state

    async def retry_failed(self, change_event_id: str) -> AnalysisExecutionState:
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
            if (
                event.status is ChangeEventStatus.PENDING
                and job.status is AnalysisJobStatus.QUEUED
            ):
                state = AnalysisExecutionState(event, job)
            elif (
                event.status is not ChangeEventStatus.FAILED
                or job.status is not AnalysisJobStatus.FAILED
            ):
                raise AnalysisJobOrchestrationError(
                    "only a failed execution may be retried"
                )
            else:
                event = requeue_change_event(event, occurred_at=self._clock())
                job = requeue_analysis_job(job)
                await uow.change_events.save(event)
                await uow.analysis_jobs.save(job)
                await uow.commit()
                state = AnalysisExecutionState(event, job)
        await self._task_enqueuer.enqueue_change(change_event_id)
        return state


async def _load_execution(
    uow: ControlUnitOfWork, change_event_id: str
) -> tuple[ChangeEvent, AnalysisJob]:
    event = await uow.change_events.get(change_event_id)
    if event is None:
        raise RecordNotFoundError(f"change event was not found: {change_event_id!r}")
    jobs = await uow.analysis_jobs.list_for_change(change_event_id)
    if len(jobs) != 1:
        raise AnalysisJobOrchestrationError(
            "ChangeEvent execution requires exactly one AnalysisJob"
        )
    job = jobs[0]
    if event.artifact_id is None or job.artifact_id != event.artifact_id:
        raise AnalysisJobOrchestrationError(
            "ChangeEvent and AnalysisJob artifact identity must match"
        )
    return event, job


__all__ = [
    "AnalysisExecutionState",
    "AnalysisJobOrchestrationError",
    "AnalysisJobOrchestrationService",
]
