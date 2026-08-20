"""Pure VWS action authorization with explicit provider-authority separation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ip_risk_agent.core.common import require_non_empty

from .models import Membership, MembershipRole, MembershipStatus, Permission, permissions_for

if TYPE_CHECKING:
    from ip_risk_agent.core.mounts.models import WorkspaceMount


class VwsAction(StrEnum):
    VWS_VIEW = "VWS_VIEW"
    RISK_VIEW = "RISK_VIEW"
    RISK_REVIEW = "RISK_REVIEW"
    SOURCE_MOUNT = "SOURCE_MOUNT"
    MOUNT_STATUS_VIEW = "MOUNT_STATUS_VIEW"
    MOUNT_RENAME = "MOUNT_RENAME"
    MOUNT_SOURCE_OPERATION = "MOUNT_SOURCE_OPERATION"
    MOUNT_RECONNECT = "MOUNT_RECONNECT"
    MOUNT_SCOPE_MANAGE = "MOUNT_SCOPE_MANAGE"
    MOUNT_DISABLE = "MOUNT_DISABLE"
    MOUNT_REMOVE = "MOUNT_REMOVE"
    VWS_SECURITY_MANAGE = "VWS_SECURITY_MANAGE"
    MEMBER_MANAGE = "MEMBER_MANAGE"
    AUDIT_VIEW = "AUDIT_VIEW"
    AUDIT_EXPORT = "AUDIT_EXPORT"
    WORKSPACE_DELETE = "WORKSPACE_DELETE"
    OWNERSHIP_TRANSFER = "OWNERSHIP_TRANSFER"


class AuthorizationReason(StrEnum):
    ALLOWED = "ALLOWED"
    NOT_MEMBER = "NOT_MEMBER"
    MEMBERSHIP_INACTIVE = "MEMBERSHIP_INACTIVE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MOUNT_REQUIRED = "MOUNT_REQUIRED"
    MOUNT_WORKSPACE_MISMATCH = "MOUNT_WORKSPACE_MISMATCH"
    MOUNT_OWNERSHIP_REQUIRED = "MOUNT_OWNERSHIP_REQUIRED"
    OWNER_ADMINISTRATION_REQUIRED = "OWNER_ADMINISTRATION_REQUIRED"
    PROVIDER_AUTHORITY_MISMATCH = "PROVIDER_AUTHORITY_MISMATCH"


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reason: AuthorizationReason
    provider_authority_required: bool = False


class AuthorizationDeniedError(PermissionError):
    def __init__(self, decision: AuthorizationDecision) -> None:
        super().__init__(decision.reason.value)
        self.decision = decision


_ACTION_PERMISSIONS: dict[VwsAction, Permission] = {
    VwsAction.VWS_VIEW: Permission.VWS_VIEW,
    VwsAction.RISK_VIEW: Permission.RISK_VIEW,
    VwsAction.RISK_REVIEW: Permission.RISK_REVIEW,
    VwsAction.SOURCE_MOUNT: Permission.SOURCE_MOUNT,
    VwsAction.MOUNT_STATUS_VIEW: Permission.VWS_VIEW,
    VwsAction.MOUNT_RENAME: Permission.OWN_SOURCE_MANAGE,
    VwsAction.MOUNT_SOURCE_OPERATION: Permission.OWN_SOURCE_MANAGE,
    VwsAction.MOUNT_RECONNECT: Permission.OWN_SOURCE_MANAGE,
    VwsAction.MOUNT_SCOPE_MANAGE: Permission.OWN_SOURCE_MANAGE,
    VwsAction.MOUNT_DISABLE: Permission.VWS_SECURITY_MANAGE,
    VwsAction.MOUNT_REMOVE: Permission.VWS_SECURITY_MANAGE,
    VwsAction.VWS_SECURITY_MANAGE: Permission.VWS_SECURITY_MANAGE,
    VwsAction.MEMBER_MANAGE: Permission.MEMBER_MANAGE,
    VwsAction.AUDIT_VIEW: Permission.AUDIT_VIEW,
    VwsAction.AUDIT_EXPORT: Permission.AUDIT_EXPORT,
    VwsAction.WORKSPACE_DELETE: Permission.WORKSPACE_DELETE,
    VwsAction.OWNERSHIP_TRANSFER: Permission.OWNERSHIP_TRANSFER,
}

_OWN_MOUNT_ACTIONS = frozenset(
    {
        VwsAction.MOUNT_RENAME,
        VwsAction.MOUNT_SOURCE_OPERATION,
        VwsAction.MOUNT_RECONNECT,
        VwsAction.MOUNT_SCOPE_MANAGE,
    }
)
_OWNER_ADMIN_ACTIONS = frozenset({VwsAction.MOUNT_DISABLE, VwsAction.MOUNT_REMOVE})
_PROVIDER_AUTHORITY_ACTIONS = frozenset(
    {
        VwsAction.SOURCE_MOUNT,
        VwsAction.MOUNT_SOURCE_OPERATION,
        VwsAction.MOUNT_RECONNECT,
        VwsAction.MOUNT_SCOPE_MANAGE,
    }
)


def authorize_vws_action(
    *,
    actor_user_id: str,
    risk_workspace_id: str,
    membership: Membership | None,
    action: VwsAction,
    mount: WorkspaceMount | None = None,
    provider_credential_owner_user_id: str | None = None,
) -> AuthorizationDecision:
    """Authorize application scope while never manufacturing source authority."""

    actor_user_id = require_non_empty(actor_user_id, "actor_user_id")
    risk_workspace_id = require_non_empty(risk_workspace_id, "risk_workspace_id")
    if (
        membership is None
        or membership.user_id != actor_user_id
        or membership.risk_workspace_id != risk_workspace_id
    ):
        return AuthorizationDecision(False, AuthorizationReason.NOT_MEMBER)
    if membership.status is not MembershipStatus.ACTIVE:
        return AuthorizationDecision(False, AuthorizationReason.MEMBERSHIP_INACTIVE)
    if _ACTION_PERMISSIONS[action] not in permissions_for(membership.role):
        return AuthorizationDecision(False, AuthorizationReason.PERMISSION_DENIED)

    if action in _OWNER_ADMIN_ACTIONS and membership.role is not MembershipRole.OWNER:
        return AuthorizationDecision(False, AuthorizationReason.OWNER_ADMINISTRATION_REQUIRED)

    if action in _OWN_MOUNT_ACTIONS or action in _OWNER_ADMIN_ACTIONS or action is VwsAction.MOUNT_STATUS_VIEW:
        if mount is None:
            return AuthorizationDecision(False, AuthorizationReason.MOUNT_REQUIRED)
        if mount.risk_workspace_id != risk_workspace_id:
            return AuthorizationDecision(False, AuthorizationReason.MOUNT_WORKSPACE_MISMATCH)

    if action in _OWN_MOUNT_ACTIONS and mount is not None:
        if mount.mounted_by_user_id != actor_user_id:
            return AuthorizationDecision(False, AuthorizationReason.MOUNT_OWNERSHIP_REQUIRED)

    provider_authority_required = action in _PROVIDER_AUTHORITY_ACTIONS
    if (
        provider_authority_required
        and provider_credential_owner_user_id is not None
        and provider_credential_owner_user_id != actor_user_id
    ):
        return AuthorizationDecision(False, AuthorizationReason.PROVIDER_AUTHORITY_MISMATCH, True)

    return AuthorizationDecision(
        True,
        AuthorizationReason.ALLOWED,
        provider_authority_required=provider_authority_required,
    )


def require_authorized(decision: AuthorizationDecision) -> None:
    if not decision.allowed:
        raise AuthorizationDeniedError(decision)
