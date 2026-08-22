"""Pure retry-safe AnalysisJob state transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from ip_risk_agent.core.common import DomainInvariantError, normalize_utc, require_non_empty

from .models import AnalysisJob, AnalysisJobStatus


def claim_analysis_job(job: AnalysisJob, *, occurred_at: datetime) -> AnalysisJob:
    if job.status is not AnalysisJobStatus.QUEUED:
        raise DomainInvariantError("only a QUEUED analysis job may be claimed")
    occurred_at = normalize_utc(occurred_at, "analysis_job_claim.occurred_at")
    return replace(job, status=AnalysisJobStatus.RUNNING, started_at=occurred_at)


def complete_analysis_job(
    job: AnalysisJob,
    *,
    status: AnalysisJobStatus,
    occurred_at: datetime,
    failure_safe: str | None = None,
) -> AnalysisJob:
    if job.status is not AnalysisJobStatus.RUNNING:
        raise DomainInvariantError("only a RUNNING analysis job may complete")
    if status not in {
        AnalysisJobStatus.SUCCEEDED,
        AnalysisJobStatus.FAILED,
        AnalysisJobStatus.INCONCLUSIVE,
    }:
        raise DomainInvariantError("analysis job completion requires a terminal status")
    occurred_at = normalize_utc(occurred_at, "analysis_job_completion.occurred_at")
    if status is AnalysisJobStatus.FAILED:
        failure_safe = require_non_empty(failure_safe or "", "analysis_job.failure_safe")
    elif status is AnalysisJobStatus.SUCCEEDED and failure_safe is not None:
        raise DomainInvariantError("SUCCEEDED analysis job cannot have failure_safe")
    return replace(
        job,
        status=status,
        completed_at=occurred_at,
        failure_safe=failure_safe,
    )


def reanalyze_analysis_job(
    job: AnalysisJob, *, reclaim_stale: bool = False
) -> AnalysisJob:
    """재검사를 위해 job 을 초기 상태로 되돌린다.

    이전 판정(analysis_outcomes)을 지운다. 남겨 두면 새 결과가 "이미 있는 결과"
    로 취급되어 수용 검사를 다르게 통과한다.
    """
    # 진행 중인지는 **이벤트의 lease** 가 정한다. worker 가 죽으면 job 은 RUNNING
    # 인 채로 남으므로 상태만 보면 좀비를 영영 풀 수 없다. 호출자가 lease 를 보고
    # 정해 넘긴다.
    if job.status is AnalysisJobStatus.QUEUED or (
        job.status is AnalysisJobStatus.RUNNING and not reclaim_stale
    ):
        raise DomainInvariantError("analysis is already in flight")
    return replace(
        job,
        status=AnalysisJobStatus.QUEUED,
        started_at=None,
        completed_at=None,
        failure_safe=None,
        analysis_outcomes={},
    )


def requeue_analysis_job(job: AnalysisJob) -> AnalysisJob:
    if job.status is not AnalysisJobStatus.FAILED:
        raise DomainInvariantError("only a FAILED analysis job may be requeued")
    return replace(
        job,
        status=AnalysisJobStatus.QUEUED,
        started_at=None,
        completed_at=None,
        failure_safe=None,
        analysis_outcomes={},
    )


def reclaim_analysis_job(job: AnalysisJob, *, occurred_at: datetime) -> AnalysisJob:
    if job.status not in {AnalysisJobStatus.RUNNING, AnalysisJobStatus.FAILED}:
        raise DomainInvariantError("only a RUNNING or FAILED analysis job may be reclaimed")
    occurred_at = normalize_utc(occurred_at, "analysis_job_reclaim.occurred_at")
    if job.started_at is not None and occurred_at < job.started_at:
        raise DomainInvariantError("analysis job reclaim cannot predate the current attempt")
    started_at = (
        occurred_at
        if job.started_at is None or occurred_at > job.started_at
        else job.started_at + timedelta(microseconds=1)
    )
    return replace(
        job,
        status=AnalysisJobStatus.RUNNING,
        started_at=started_at,
        completed_at=None,
        failure_safe=None,
        analysis_outcomes={},
    )


__all__ = [
    "claim_analysis_job",
    "complete_analysis_job",
    "reclaim_analysis_job",
    "reanalyze_analysis_job",
    "requeue_analysis_job",
]
