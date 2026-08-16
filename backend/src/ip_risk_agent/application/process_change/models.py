"""Canonical ChangeEvent state used by retry-safe intake."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from iprisk_contracts import ChangeType, SourceType

from ip_risk_agent.core.common import (
    DomainInvariantError,
    freeze_safe_mapping,
    normalize_utc,
    require_chronological,
    require_non_empty,
    stable_key,
)


class ChangeEventStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


def change_event_id_for(event_fingerprint: str) -> str:
    return stable_key("change", (event_fingerprint,))


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    id: str
    event_fingerprint: str
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    source_artifact_id: str
    source_type: SourceType
    change_type: ChangeType
    revision: str | None
    previous_revision: str | None
    observed_at: datetime
    status: ChangeEventStatus
    attempts: int
    created_at: datetime
    updated_at: datetime
    artifact_id: str | None = None
    provider_event_id: str | None = None
    last_error_safe: str | None = None
    safe_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "event_fingerprint",
            "risk_workspace_id",
            "mount_id",
            "source_workspace_id",
            "source_artifact_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"change_event.{field_name}"),
            )
        if self.attempts < 0:
            raise DomainInvariantError("change_event.attempts cannot be negative")
        observed_at = normalize_utc(self.observed_at, "change_event.observed_at")
        created_at = normalize_utc(self.created_at, "change_event.created_at")
        updated_at = normalize_utc(self.updated_at, "change_event.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="change_event.created_at",
            later_name="change_event.updated_at",
        )
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(
            self,
            "safe_metadata",
            freeze_safe_mapping(self.safe_metadata, "change_event.safe_metadata"),
        )
        if self.last_error_safe is not None:
            object.__setattr__(
                self,
                "last_error_safe",
                require_non_empty(self.last_error_safe, "change_event.last_error_safe"),
            )
        if self.status is ChangeEventStatus.PENDING:
            if self.last_error_safe is not None:
                raise DomainInvariantError("PENDING change event cannot have last_error_safe")
        elif self.status is ChangeEventStatus.PROCESSING:
            if self.attempts < 1 or self.last_error_safe is not None:
                raise DomainInvariantError(
                    "PROCESSING change event requires an attempt and no last_error_safe"
                )
        elif self.status is ChangeEventStatus.FAILED:
            if self.attempts < 1 or self.last_error_safe is None:
                raise DomainInvariantError(
                    "FAILED change event requires an attempt and last_error_safe"
                )
        elif self.last_error_safe is not None:
            raise DomainInvariantError("DONE change event cannot have last_error_safe")
