"""Risk Workspace domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ip_risk_agent.core.common import (
    DomainInvariantError,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class RiskWorkspaceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class RiskWorkspace:
    id: str
    name: str
    owner_user_id: str
    security_policy_version: str
    retention_policy_version: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    status: RiskWorkspaceStatus = RiskWorkspaceStatus.ACTIVE
    global_ignore_text: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "owner_user_id",
            "security_policy_version",
            "retention_policy_version",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"risk_workspace.{field_name}"),
            )
        created_at = normalize_utc(self.created_at, "risk_workspace.created_at")
        updated_at = normalize_utc(self.updated_at, "risk_workspace.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="risk_workspace.created_at",
            later_name="risk_workspace.updated_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        if "\x00" in self.global_ignore_text:
            raise DomainInvariantError(
                "risk_workspace.global_ignore_text cannot contain NUL"
            )
        if len(self.global_ignore_text.encode("utf-8")) > 64_000:
            raise DomainInvariantError(
                "risk_workspace.global_ignore_text exceeds 64 KiB"
            )
