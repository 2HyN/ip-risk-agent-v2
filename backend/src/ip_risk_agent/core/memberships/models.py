"""VWS membership roles and their application permissions."""

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


class MembershipRole(StrEnum):
    OWNER = "OWNER"
    SOURCE_MANAGER = "SOURCE_MANAGER"
    RISK_REVIEWER = "RISK_REVIEWER"
    VIEWER = "VIEWER"


class MembershipStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


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


@dataclass(frozen=True, slots=True)
class MembershipInvitation:
    """Pending email invitation persisted in the memberships storage boundary."""

    id: str
    risk_workspace_id: str
    email: str
    role: MembershipRole
    status: InvitationStatus
    invited_by: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "risk_workspace_id", "invited_by"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"membership_invitation.{field_name}"),
            )
        normalized_email = require_non_empty(self.email, "membership_invitation.email").casefold()
        local, separator, domain = normalized_email.rpartition("@")
        if not separator or not local or not domain:
            raise DomainInvariantError(
                "membership_invitation.email must contain a local part and domain"
            )
        if self.role is MembershipRole.OWNER:
            raise DomainInvariantError("OWNER must be assigned through ownership transfer")
        object.__setattr__(self, "email", normalized_email)
        created_at = normalize_utc(self.created_at, "membership_invitation.created_at")
        updated_at = normalize_utc(self.updated_at, "membership_invitation.updated_at")
        require_chronological(
            created_at,
            updated_at,
            earlier_name="membership_invitation.created_at",
            later_name="membership_invitation.updated_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        if self.expires_at is not None:
            expires_at = normalize_utc(self.expires_at, "membership_invitation.expires_at")
            require_chronological(
                created_at,
                expires_at,
                earlier_name="membership_invitation.created_at",
                later_name="membership_invitation.expires_at",
            )
            object.__setattr__(self, "expires_at", expires_at)
