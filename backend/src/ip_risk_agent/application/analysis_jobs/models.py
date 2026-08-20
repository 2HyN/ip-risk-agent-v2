"""Retry-safe AnalysisJob aggregate model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from iprisk_contracts import AnalysisCoverage, AnalysisStatus, AnalysisType

from ip_risk_agent.core.common import (
    DomainInvariantError,
    normalize_utc,
    require_chronological,
    require_non_empty,
    stable_key,
)


class AnalysisJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


def analysis_job_id_for(change_event_id: str) -> str:
    return stable_key("analysis-job", (change_event_id,))


@dataclass(frozen=True, slots=True)
class ProviderFailureSummary:
    provider: str
    category: str
    retryable: bool
    safe_message: str

    def __post_init__(self) -> None:
        for field_name in ("provider", "category", "safe_message"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(
                    getattr(self, field_name),
                    f"provider_failure_summary.{field_name}",
                ),
            )


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    analysis_type: AnalysisType
    result_fingerprint: str
    status: AnalysisStatus
    coverage: AnalysisCoverage
    analyzer_version: str
    started_at: datetime
    completed_at: datetime
    provider_failures: tuple[ProviderFailureSummary, ...] = ()
    model_id: str | None = None
    prompt_version: str | None = None
    policy_version: str | None = None
    rag_corpus_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("result_fingerprint", "analyzer_version"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(
                    getattr(self, field_name), f"analysis_outcome.{field_name}"
                ),
            )
        started_at = normalize_utc(self.started_at, "analysis_outcome.started_at")
        completed_at = normalize_utc(self.completed_at, "analysis_outcome.completed_at")
        require_chronological(
            started_at,
            completed_at,
            earlier_name="analysis_outcome.started_at",
            later_name="analysis_outcome.completed_at",
        )
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        object.__setattr__(self, "provider_failures", tuple(self.provider_failures))
        if any(
            not isinstance(failure, ProviderFailureSummary)
            for failure in self.provider_failures
        ):
            raise DomainInvariantError(
                "analysis_outcome provider failures must be safe summaries"
            )
        if (
            self.status is not AnalysisStatus.SUCCEEDED
            and self.coverage is AnalysisCoverage.COMPLETE
        ):
            raise DomainInvariantError(
                "only a SUCCEEDED analysis outcome may have COMPLETE coverage"
            )
        for field_name in (
            "model_id",
            "prompt_version",
            "policy_version",
            "rag_corpus_version",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    require_non_empty(value, f"analysis_outcome.{field_name}"),
                )


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
    analysis_outcomes: Mapping[AnalysisType, AnalysisOutcome] = field(
        default_factory=dict
    )

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
        if self.failure_safe is not None:
            object.__setattr__(
                self,
                "failure_safe",
                require_non_empty(self.failure_safe, "analysis_job.failure_safe"),
            )
        outcomes: dict[AnalysisType, AnalysisOutcome] = {}
        for analysis_type, outcome in self.analysis_outcomes.items():
            if not isinstance(analysis_type, AnalysisType):
                raise DomainInvariantError(
                    "analysis_job outcome keys must be AnalysisType values"
                )
            if outcome.analysis_type is not analysis_type:
                raise DomainInvariantError(
                    "analysis_job outcome key must match outcome analysis_type"
                )
            if analysis_type not in self.requested_analysis_types:
                raise DomainInvariantError(
                    "analysis_job outcome must be a requested analysis type"
                )
            outcomes[analysis_type] = outcome
        object.__setattr__(self, "analysis_outcomes", MappingProxyType(outcomes))
        if self.status is AnalysisJobStatus.QUEUED:
            if self.started_at is not None or self.completed_at is not None:
                raise DomainInvariantError("QUEUED analysis job cannot have execution timestamps")
            if self.failure_safe is not None:
                raise DomainInvariantError("QUEUED analysis job cannot have failure_safe")
            if outcomes:
                raise DomainInvariantError("QUEUED analysis job cannot have outcomes")
        elif self.status is AnalysisJobStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None:
                raise DomainInvariantError(
                    "RUNNING analysis job requires started_at and forbids completed_at"
                )
            if self.failure_safe is not None:
                raise DomainInvariantError("RUNNING analysis job cannot have failure_safe")
        else:
            if self.started_at is None or self.completed_at is None:
                raise DomainInvariantError(
                    "terminal analysis job requires started_at and completed_at"
                )
            if self.status is AnalysisJobStatus.FAILED and self.failure_safe is None:
                raise DomainInvariantError("FAILED analysis job requires failure_safe")
            if self.status is AnalysisJobStatus.SUCCEEDED and self.failure_safe is not None:
                raise DomainInvariantError("SUCCEEDED analysis job cannot have failure_safe")
            if outcomes and set(outcomes) != set(self.requested_analysis_types):
                raise DomainInvariantError(
                    "terminal result-bearing job requires every requested outcome"
                )
            if self.status is AnalysisJobStatus.SUCCEEDED and any(
                outcome.status is not AnalysisStatus.SUCCEEDED
                or outcome.coverage is not AnalysisCoverage.COMPLETE
                for outcome in outcomes.values()
            ):
                raise DomainInvariantError(
                    "SUCCEEDED analysis job requires authoritative outcomes"
                )
