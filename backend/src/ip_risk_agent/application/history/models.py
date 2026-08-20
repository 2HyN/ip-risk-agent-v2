"""Read-only, safe projections over the three canonical history streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from ip_risk_agent.core.common import (
    ActorType,
    freeze_safe_mapping,
    normalize_utc,
    require_non_empty,
)
from ip_risk_agent.core.risk import ReviewDisposition, RiskLifecycleState


class HistoryStream(StrEnum):
    RISK = "RISK"
    AUDIT = "AUDIT"
    SOURCE_ACCESS = "SOURCE_ACCESS"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: str
    stream: HistoryStream
    event_type: str
    risk_workspace_id: str
    occurred_at: datetime
    actor_type: ActorType
    actor_user_id: str | None = None
    risk_id: str | None = None
    artifact_id: str | None = None
    mount_id: str | None = None
    metadata_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "event_type", "risk_workspace_id"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"history_entry.{field_name}"),
            )
        object.__setattr__(
            self,
            "occurred_at",
            normalize_utc(self.occurred_at, "history_entry.occurred_at"),
        )
        object.__setattr__(
            self,
            "metadata_safe",
            freeze_safe_mapping(self.metadata_safe, "history_entry.metadata_safe"),
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "stream": self.stream.value,
            "event_type": self.event_type,
            "risk_workspace_id": self.risk_workspace_id,
            "occurred_at": self.occurred_at.isoformat(),
            "actor_type": self.actor_type.value,
            "actor_user_id": self.actor_user_id,
            "risk_id": self.risk_id,
            "artifact_id": self.artifact_id,
            "mount_id": self.mount_id,
            "metadata_safe": _json_compatible(self.metadata_safe),
        }


@dataclass(frozen=True, slots=True)
class RiskTimeline:
    risk_id: str
    risk_workspace_id: str
    lifecycle_state: RiskLifecycleState
    review_disposition: ReviewDisposition
    review_version: int
    entries: tuple[HistoryEntry, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceActivity:
    risk_workspace_id: str
    entries: tuple[HistoryEntry, ...]


@dataclass(frozen=True, slots=True)
class HistoryExport:
    risk_workspace_id: str
    generated_at: datetime
    entries: tuple[HistoryEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "generated_at",
            normalize_utc(self.generated_at, "history_export.generated_at"),
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "risk_workspace_id": self.risk_workspace_id,
            "generated_at": self.generated_at.isoformat(),
            "entries": [entry.to_safe_dict() for entry in self.entries],
        }


def _json_compatible(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_compatible(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_json_compatible(nested) for nested in value]
    return value


__all__ = [
    "HistoryEntry",
    "HistoryExport",
    "HistoryStream",
    "RiskTimeline",
    "WorkspaceActivity",
]
