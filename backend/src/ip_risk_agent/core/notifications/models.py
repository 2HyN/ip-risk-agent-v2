"""MVP Firestore/in-app notification model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from ip_risk_agent.core.common import (
    DomainInvariantError,
    freeze_safe_mapping,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class NotificationType(StrEnum):
    RISK_HIGH_DETECTED = "RISK_HIGH_DETECTED"
    RISK_REOPENED = "RISK_REOPENED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    MOUNT_REAUTH_REQUIRED = "MOUNT_REAUTH_REQUIRED"
    SOURCE_OFFLINE = "SOURCE_OFFLINE"


class NotificationStatus(StrEnum):
    UNREAD = "UNREAD"
    READ = "READ"


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    user_id: str
    risk_workspace_id: str
    notification_type: NotificationType
    status: NotificationStatus
    created_at: datetime
    read_at: datetime | None = None
    metadata_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "user_id", "risk_workspace_id"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"notification.{field_name}"),
            )
        object.__setattr__(
            self,
            "created_at",
            normalize_utc(self.created_at, "notification.created_at"),
        )
        if self.status is NotificationStatus.READ and self.read_at is None:
            raise DomainInvariantError("READ notification requires read_at")
        if self.status is NotificationStatus.UNREAD and self.read_at is not None:
            raise DomainInvariantError("UNREAD notification cannot have read_at")
        if self.read_at is not None:
            read_at = normalize_utc(self.read_at, "notification.read_at")
            require_chronological(
                self.created_at,
                read_at,
                earlier_name="notification.created_at",
                later_name="notification.read_at",
            )
            object.__setattr__(
                self,
                "read_at",
                read_at,
            )
        object.__setattr__(
            self,
            "metadata_safe",
            freeze_safe_mapping(self.metadata_safe, "notification.metadata_safe"),
        )
