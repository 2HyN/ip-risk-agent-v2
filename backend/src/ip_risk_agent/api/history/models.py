"""Strict public DTOs for safe Control history projections."""

from __future__ import annotations

from datetime import datetime

from ip_risk_agent.application.history import HistoryEntry, HistoryStream
from ip_risk_agent.core.common import ActorType

from ..common import StrictApiModel


class HistoryEntryResponse(StrictApiModel):
    id: str
    stream: HistoryStream
    event_type: str
    risk_workspace_id: str
    occurred_at: datetime
    actor_type: ActorType
    actor_user_id: str | None
    risk_id: str | None
    artifact_id: str | None
    mount_id: str | None
    metadata_safe: dict[str, object]

    @classmethod
    def from_entry(cls, entry: HistoryEntry) -> "HistoryEntryResponse":
        return cls.model_validate(entry.to_safe_dict())


__all__ = ["HistoryEntryResponse"]
