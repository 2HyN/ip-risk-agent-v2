"""Canonical Risk projection and append-only history models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from iprisk_contracts import AnalysisType, ReviewPriority

from ip_risk_agent.core.common import (
    ActorType,
    DomainInvariantError,
    freeze_safe_mapping,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class RiskLifecycleState(StrEnum):
    NEW = "NEW"
    EXISTING = "EXISTING"
    RESOLVED = "RESOLVED"


class ReviewDisposition(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    MONITORING = "MONITORING"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    EXCLUDED = "EXCLUDED"


class RiskEventType(StrEnum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    EVIDENCE_UPDATED = "EVIDENCE_UPDATED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    REVIEW_DISPOSITION_CHANGED = "REVIEW_DISPOSITION_CHANGED"


@dataclass(frozen=True, slots=True)
class Risk:
    id: str
    risk_workspace_id: str
    artifact_id: str
    analysis_type: AnalysisType
    risk_key: str
    lifecycle_state: RiskLifecycleState
    review_disposition: ReviewDisposition
    review_priority: ReviewPriority
    summary: str
    first_seen_at: datetime
    last_seen_at: datetime
    latest_analysis_job_id: str
    updated_at: datetime
    resolved_at: datetime | None = None
    latest_evidence_revision: str | None = None
    review_version: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "risk_workspace_id",
            "artifact_id",
            "risk_key",
            "summary",
            "latest_analysis_job_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"risk.{field_name}"),
            )
        first_seen_at = normalize_utc(self.first_seen_at, "risk.first_seen_at")
        last_seen_at = normalize_utc(self.last_seen_at, "risk.last_seen_at")
        updated_at = normalize_utc(self.updated_at, "risk.updated_at")
        require_chronological(
            first_seen_at,
            last_seen_at,
            earlier_name="risk.first_seen_at",
            later_name="risk.last_seen_at",
        )
        require_chronological(
            first_seen_at,
            updated_at,
            earlier_name="risk.first_seen_at",
            later_name="risk.updated_at",
        )
        object.__setattr__(self, "first_seen_at", first_seen_at)
        object.__setattr__(self, "last_seen_at", last_seen_at)
        object.__setattr__(self, "updated_at", updated_at)
        if self.lifecycle_state is RiskLifecycleState.RESOLVED:
            if self.resolved_at is None:
                raise DomainInvariantError("risk.resolved_at is required for RESOLVED risks")
            resolved_at = normalize_utc(self.resolved_at, "risk.resolved_at")
            require_chronological(
                first_seen_at,
                resolved_at,
                earlier_name="risk.first_seen_at",
                later_name="risk.resolved_at",
            )
            require_chronological(
                last_seen_at,
                resolved_at,
                earlier_name="risk.last_seen_at",
                later_name="risk.resolved_at",
            )
            require_chronological(
                resolved_at,
                updated_at,
                earlier_name="risk.resolved_at",
                later_name="risk.updated_at",
            )
            object.__setattr__(self, "resolved_at", resolved_at)
        elif self.resolved_at is not None:
            raise DomainInvariantError("active risks cannot have risk.resolved_at")
        if isinstance(self.review_version, bool) or self.review_version < 0:
            raise DomainInvariantError("risk.review_version cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskEvidence:
    id: str
    risk_id: str
    analysis_job_id: str
    evidence_id_from_result: str
    evidence_type: str
    excerpt: str
    reference: str
    source_revision: str
    created_at: datetime
    metadata_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "risk_id",
            "analysis_job_id",
            "evidence_id_from_result",
            "evidence_type",
            "reference",
            "source_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"risk_evidence.{field_name}"),
            )
        object.__setattr__(
            self,
            "created_at",
            normalize_utc(self.created_at, "risk_evidence.created_at"),
        )
        object.__setattr__(
            self,
            "metadata_safe",
            freeze_safe_mapping(self.metadata_safe, "risk_evidence.metadata_safe"),
        )


@dataclass(frozen=True, slots=True)
class RiskEvent:
    id: str
    risk_id: str
    event_type: RiskEventType
    actor_type: ActorType
    occurred_at: datetime
    actor_user_id: str | None = None
    previous_state_safe: Mapping[str, object] = field(default_factory=dict)
    new_state_safe: Mapping[str, object] = field(default_factory=dict)
    analysis_job_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    reason_safe: str | None = None
    previous_event_hash: str | None = None
    event_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_non_empty(self.id, "risk_event.id"))
        object.__setattr__(self, "risk_id", require_non_empty(self.risk_id, "risk_event.risk_id"))
        if self.actor_type is ActorType.USER and not self.actor_user_id:
            raise DomainInvariantError("user-authored RiskEvent requires actor_user_id")
        evidence_refs = tuple(
            require_non_empty(reference, "risk_event.evidence_refs item")
            for reference in self.evidence_refs
        )
        if len(evidence_refs) != len(set(evidence_refs)):
            raise DomainInvariantError("risk_event.evidence_refs must be unique")
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(
            self,
            "occurred_at",
            normalize_utc(self.occurred_at, "risk_event.occurred_at"),
        )
        object.__setattr__(
            self,
            "previous_state_safe",
            freeze_safe_mapping(self.previous_state_safe, "risk_event.previous_state_safe"),
        )
        object.__setattr__(
            self,
            "new_state_safe",
            freeze_safe_mapping(self.new_state_safe, "risk_event.new_state_safe"),
        )
