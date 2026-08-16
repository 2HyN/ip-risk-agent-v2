"""Transactional claim/finish/fail orchestration for one ChangeEvent job."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ip_risk_agent.application.repositories import (
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.common import DomainInvariantError

from ip_risk_agent.application.process_change.models import (
    ChangeEvent,
    ChangeEventStatus,
)
from ip_risk_agent.application.process_change.queue import TaskEnqueuer
from ip_risk_agent.application.process_change.transitions import (
    claim_change_event,
    complete_change_event,
    fail_change_event,
    requeue_change_event,
)

from .models import AnalysisJob, AnalysisJobStatus
from .transitions import (
    claim_analysis_job,
    complete_analysis_job,
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
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._task_enqueuer = task_enqueuer
        self._clock = clock

    async def claim(self, change_event_id: str) -> AnalysisExecutionState | None:
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
            if (
                event.status is ChangeEventStatus.PROCESSING
                and job.status is AnalysisJobStatus.RUNNING
            ):
                return None
            if event.status is ChangeEventStatus.DONE and job.status in {
                AnalysisJobStatus.SUCCEEDED,
                AnalysisJobStatus.INCONCLUSIVE,
            }:
                return None
            if event.status is not ChangeEventStatus.PENDING:
                raise AnalysisJobOrchestrationError(
                    "only a PENDING ChangeEvent may be claimed"
                )
            if job.status is not AnalysisJobStatus.QUEUED:
                raise AnalysisJobOrchestrationError(
                    "PENDING ChangeEvent requires QUEUED AnalysisJob"
                )
            occurred_at = self._clock()
            event = claim_change_event(event, occurred_at=occurred_at)
            job = claim_analysis_job(job, occurred_at=occurred_at)
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
    ) -> AnalysisExecutionState:
        async with self._unit_of_work_factory() as uow:
            event, job = await _load_execution(uow, change_event_id)
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
