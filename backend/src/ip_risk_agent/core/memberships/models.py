"""VWS membership roles and their application permissions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ip_risk_agent.core.common import normalize_utc, require_chronological, require_non_empty


class MembershipRole(StrEnum):
    OWNER = "OWNER"
    SOURCE_MANAGER = "SOURCE_MANAGER"
    RISK_REVIEWER = "RISK_REVIEWER"
    VIEWER = "VIEWER"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class Permission(StrEnum):
    VWS_VIEW = "VWS_VIEW"
    RISK_VIEW = "RISK_VIEW"
    RISK_REVIEW = "RISK_REVIEW"
    SOURCE_MOUNT = "SOURCE_MOUNT"
    OWN_SOURCE_MANAGE = "OWN_SOURCE_MANAGE"
    VWS_SECURITY_MANAGE = "VWS_SECURITY_MANAGE"
    MEMBER_MANAGE = "MEMBER_MANAGE"
    AUDIT_VIEW = "AUDIT_VIEW"
    AUDIT_EXPORT = "AUDIT_EXPORT"
    WORKSPACE_DELETE = "WORKSPACE_DELETE"
    OWNERSHIP_TRANSFER = "OWNERSHIP_TRANSFER"


_VIEWER_PERMISSIONS = frozenset({Permission.VWS_VIEW, Permission.RISK_VIEW})
_REVIEWER_PERMISSIONS = _VIEWER_PERMISSIONS | {Permission.RISK_REVIEW}
_SOURCE_MANAGER_PERMISSIONS = _REVIEWER_PERMISSIONS | {
    Permission.SOURCE_MOUNT,
    Permission.OWN_SOURCE_MANAGE,
}
_ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.VIEWER: _VIEWER_PERMISSIONS,
    MembershipRole.RISK_REVIEWER: _REVIEWER_PERMISSIONS,
    MembershipRole.SOURCE_MANAGER: _SOURCE_MANAGER_PERMISSIONS,
    MembershipRole.OWNER: frozenset(Permission),
}


def permissions_for(role: MembershipRole) -> frozenset[Permission]:
    """Return immutable application permissions; raw-source access is absent by design."""

    return _ROLE_PERMISSIONS[role]


@dataclass(frozen=True, slots=True)
class Membership:
    id: str
    risk_workspace_id: str
    user_id: str
    role: MembershipRole
    status: MembershipStatus
    invited_by: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("id", "risk_workspace_id", "user_id", "invited_by"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"membership.{field_name}"),
            )
        created_at = normalize_utc(self.created_at, "membership.created_at")
        updated_at = normalize_utc(self.updated_at, "membership.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="membership.created_at",
            later_name="membership.updated_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
