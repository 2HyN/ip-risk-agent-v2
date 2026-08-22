"""Pure retry-safe AnalysisJob state transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

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


def requeue_analysis_job(
    job: AnalysisJob, *, allow_inconclusive: bool = False
) -> AnalysisJob:
    """FAILED 작업을 다시 줄 세운다.

    ``allow_inconclusive`` 는 미결 실행의 재개용이다. INCONCLUSIVE 는
    "권위 있는 결론이 없다"는 뜻이므로 다시 돌려도 사실이 뒤집히지 않는다.
    """
    allowed = {AnalysisJobStatus.FAILED}
    if allow_inconclusive:
        allowed.add(AnalysisJobStatus.INCONCLUSIVE)
    if job.status not in allowed:
        raise DomainInvariantError("only a FAILED analysis job may be requeued")
    return replace(
        job,
        status=AnalysisJobStatus.QUEUED,
        started_at=None,
        completed_at=None,
        failure_safe=None,
        analysis_outcomes={},
    )


__all__ = [
    "claim_analysis_job",
    "complete_analysis_job",
    "requeue_analysis_job",
]
