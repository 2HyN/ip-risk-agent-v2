"""Retry-safe AnalysisJob aggregate model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from iprisk_contracts import AnalysisType

from ip_risk_agent.core.common import (
    DomainInvariantError,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class AnalysisJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    id: str
    change_event_id: str
    artifact_id: str
    revision: str
    requested_analysis_types: tuple[AnalysisType, ...]
    status: AnalysisJobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_safe: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "change_event_id", "artifact_id", "revision"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"analysis_job.{field_name}"),
            )
        if not self.requested_analysis_types:
            raise DomainInvariantError("analysis_job.requested_analysis_types must not be empty")
        if len(self.requested_analysis_types) != len(set(self.requested_analysis_types)):
            raise DomainInvariantError("analysis_job.requested_analysis_types must be unique")
        created_at = normalize_utc(self.created_at, "analysis_job.created_at")
        object.__setattr__(self, "created_at", created_at)
        started_at = None
        if self.started_at is not None:
            started_at = normalize_utc(self.started_at, "analysis_job.started_at")
            require_chronological(
                created_at,
                started_at,
                earlier_name="analysis_job.created_at",
                later_name="analysis_job.started_at",
            )
            object.__setattr__(self, "started_at", started_at)
        if self.completed_at is not None:
            completed_at = normalize_utc(self.completed_at, "analysis_job.completed_at")
            require_chronological(
                started_at or created_at,
                completed_at,
                earlier_name="analysis_job.started_at",
                later_name="analysis_job.completed_at",
            )
            object.__setattr__(self, "completed_at", completed_at)
