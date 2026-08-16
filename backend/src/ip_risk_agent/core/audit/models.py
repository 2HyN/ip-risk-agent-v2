"""Control-owned operational audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from iprisk_contracts import SourceAccessType

from ip_risk_agent.core.common import (
    ActorType,
    DomainInvariantError,
    freeze_safe_mapping,
    normalize_utc,
    require_non_empty,
)


class AuditEventType(StrEnum):
    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    WORKSPACE_UPDATED = "WORKSPACE_UPDATED"
    MEMBER_INVITED = "MEMBER_INVITED"
    MEMBER_ROLE_CHANGED = "MEMBER_ROLE_CHANGED"
    MEMBER_REMOVED = "MEMBER_REMOVED"
    SOURCE_CONNECTED = "SOURCE_CONNECTED"
    SOURCE_DISCONNECTED = "SOURCE_DISCONNECTED"
    MOUNT_CREATED = "MOUNT_CREATED"
    MOUNT_RENAMED = "MOUNT_RENAMED"
    MOUNT_DISABLED = "MOUNT_DISABLED"
    MOUNT_REMOVED = "MOUNT_REMOVED"
    SECURITY_POLICY_CHANGED = "SECURITY_POLICY_CHANGED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    risk_workspace_id: str
    event_type: AuditEventType
    actor_type: ActorType
    occurred_at: datetime
    actor_user_id: str | None = None
    metadata_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "risk_workspace_id"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"audit_event.{field_name}"),
            )
        if self.actor_type is ActorType.USER and not self.actor_user_id:
            raise DomainInvariantError("user-authored AuditEvent requires actor_user_id")
        object.__setattr__(
            self,
            "occurred_at",
            normalize_utc(self.occurred_at, "audit_event.occurred_at"),
        )
        object.__setattr__(
            self,
            "metadata_safe",
            freeze_safe_mapping(self.metadata_safe, "audit_event.metadata_safe"),
        )


@dataclass(frozen=True, slots=True)
class SourceAccessEvent:
    id: str
    risk_workspace_id: str
    mount_id: str
    artifact_id: str
    access_type: SourceAccessType
    revision: str
    content_bytes: int
    occurred_at: datetime
    analysis_job_id: str | None = None
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "risk_workspace_id", "mount_id", "artifact_id", "revision"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"source_access_event.{field_name}"),
            )
        if self.content_bytes < 0:
            raise DomainInvariantError("source_access_event.content_bytes cannot be negative")
        object.__setattr__(
            self,
            "occurred_at",
            normalize_utc(self.occurred_at, "source_access_event.occurred_at"),
        )
