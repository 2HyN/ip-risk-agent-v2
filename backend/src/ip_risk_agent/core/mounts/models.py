"""Control-owned source metadata and Workspace Mount models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from iprisk_contracts import SourceType

from ip_risk_agent.core.common import (
    DomainInvariantError,
    freeze_safe_mapping,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class SourceConnectionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    DISCONNECTED = "DISCONNECTED"
    DISABLED = "DISABLED"


class SourceWorkspaceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    SOURCE_OFFLINE = "SOURCE_OFFLINE"
    DISABLED = "DISABLED"


class MountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    MANAGER_ACTION_REQUIRED = "MANAGER_ACTION_REQUIRED"
    SOURCE_OFFLINE = "SOURCE_OFFLINE"
    DISABLED = "DISABLED"


def normalize_mount_alias(alias: str) -> str:
    """Normalize the presentation alias while rejecting path-like ambiguity."""

    normalized = require_non_empty(alias, "workspace_mount.alias").strip("/")
    if not normalized or "\\" in normalized or "//" in normalized:
        raise DomainInvariantError("workspace_mount.alias must be one logical path segment")
    if "/" in normalized or normalized in {".", ".."}:
        raise DomainInvariantError("workspace_mount.alias must be one logical path segment")
    return normalized


def mount_alias_key(alias: str) -> str:
    """Return the case-insensitive uniqueness key for an alias."""

    return normalize_mount_alias(alias).casefold()


@dataclass(frozen=True, slots=True)
class SourceConnection:
    id: str
    provider: SourceType
    authorized_by_user_id: str
    status: SourceConnectionStatus
    created_at: datetime
    updated_at: datetime
    provider_subject: str | None = None
    provider_account_label: str | None = None
    credential_ref: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for field_name in ("id", "authorized_by_user_id"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"source_connection.{field_name}"),
            )
        created_at = normalize_utc(self.created_at, "source_connection.created_at")
        updated_at = normalize_utc(self.updated_at, "source_connection.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="source_connection.created_at",
            later_name="source_connection.updated_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)


@dataclass(frozen=True, slots=True)
class SourceWorkspace:
    id: str
    source_connection_id: str
    source_type: SourceType
    external_scope_id: str
    display_name: str
    status: SourceWorkspaceStatus
    created_at: datetime
    updated_at: datetime
    tracking_config_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "source_connection_id",
            "external_scope_id",
            "display_name",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"source_workspace.{field_name}"),
            )
        created_at = normalize_utc(self.created_at, "source_workspace.created_at")
        updated_at = normalize_utc(self.updated_at, "source_workspace.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="source_workspace.created_at",
            later_name="source_workspace.updated_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(
            self,
            "tracking_config_safe",
            freeze_safe_mapping(
                self.tracking_config_safe,
                "source_workspace.tracking_config_safe",
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceMount:
    id: str
    risk_workspace_id: str
    source_workspace_id: str
    alias: str
    mounted_by_user_id: str
    source_connection_id: str
    status: MountStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "risk_workspace_id",
            "source_workspace_id",
            "mounted_by_user_id",
            "source_connection_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"workspace_mount.{field_name}"),
            )
        object.__setattr__(self, "alias", normalize_mount_alias(self.alias))
        created_at = normalize_utc(self.created_at, "workspace_mount.created_at")
        updated_at = normalize_utc(self.updated_at, "workspace_mount.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="workspace_mount.created_at",
            later_name="workspace_mount.updated_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
