from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ip_risk_agent.core.memberships import (
    AuthorizationReason,
    Membership,
    MembershipRole,
    MembershipStatus,
    VwsAction,
    authorize_vws_action,
    membership_id_for,
)
from ip_risk_agent.core.mounts import MountStatus, WorkspaceMount

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)


def make_membership(
    role: MembershipRole,
    *,
    user_id: str = "user-1",
    vws_id: str = "vws-1",
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> Membership:
    return Membership(
        id=membership_id_for(vws_id, user_id),
        risk_workspace_id=vws_id,
        user_id=user_id,
        role=role,
        status=status,
        invited_by="owner-1",
        created_at=NOW,
        updated_at=NOW,
    )


def make_mount(*, owner: str = "user-1", vws_id: str = "vws-1") -> WorkspaceMount:
    return WorkspaceMount(
        id="mount-1",
        risk_workspace_id=vws_id,
        source_workspace_id="source-workspace-1",
        alias="backend",
        mounted_by_user_id=owner,
        source_connection_id="connection-1",
        status=MountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    ("role", "action", "allowed"),
    [
        (MembershipRole.VIEWER, VwsAction.RISK_VIEW, True),
        (MembershipRole.VIEWER, VwsAction.RISK_REVIEW, False),
        (MembershipRole.RISK_REVIEWER, VwsAction.RISK_REVIEW, True),
        (MembershipRole.RISK_REVIEWER, VwsAction.SOURCE_MOUNT, False),
        (MembershipRole.SOURCE_MANAGER, VwsAction.SOURCE_MOUNT, True),
        (MembershipRole.SOURCE_MANAGER, VwsAction.MEMBER_MANAGE, False),
        (MembershipRole.OWNER, VwsAction.MEMBER_MANAGE, True),
        (MembershipRole.OWNER, VwsAction.AUDIT_EXPORT, True),
    ],
)
def test_role_action_matrix(role: MembershipRole, action: VwsAction, allowed: bool) -> None:
    membership = make_membership(role)
    decision = authorize_vws_action(
        actor_user_id=membership.user_id,
        risk_workspace_id=membership.risk_workspace_id,
        membership=membership,
        action=action,
    )
    assert decision.allowed is allowed


_ROLE_ACTIONS = {
    MembershipRole.VIEWER: {
        VwsAction.VWS_VIEW,
        VwsAction.RISK_VIEW,
        VwsAction.MOUNT_STATUS_VIEW,
    },
    MembershipRole.RISK_REVIEWER: {
        VwsAction.VWS_VIEW,
        VwsAction.RISK_VIEW,
        VwsAction.RISK_REVIEW,
        VwsAction.MOUNT_STATUS_VIEW,
    },
    MembershipRole.SOURCE_MANAGER: {
        VwsAction.VWS_VIEW,
        VwsAction.RISK_VIEW,
        VwsAction.RISK_REVIEW,
        VwsAction.SOURCE_MOUNT,
        VwsAction.MOUNT_STATUS_VIEW,
        VwsAction.MOUNT_RENAME,
        VwsAction.MOUNT_SOURCE_OPERATION,
        VwsAction.MOUNT_RECONNECT,
        VwsAction.MOUNT_SCOPE_MANAGE,
    },
    MembershipRole.OWNER: set(VwsAction),
}


@pytest.mark.parametrize("role", list(MembershipRole))
@pytest.mark.parametrize("action", list(VwsAction))
def test_exhaustive_role_action_matrix(
    role: MembershipRole,
    action: VwsAction,
) -> None:
    membership = make_membership(role)
    decision = authorize_vws_action(
        actor_user_id=membership.user_id,
        risk_workspace_id=membership.risk_workspace_id,
        membership=membership,
        action=action,
        mount=make_mount(owner=membership.user_id),
        provider_credential_owner_user_id=membership.user_id,
    )
    assert decision.allowed is (action in _ROLE_ACTIONS[role])


def test_inactive_membership_is_denied() -> None:
    membership = make_membership(MembershipRole.OWNER, status=MembershipStatus.REMOVED)
    decision = authorize_vws_action(
        actor_user_id=membership.user_id,
        risk_workspace_id=membership.risk_workspace_id,
        membership=membership,
        action=VwsAction.MEMBER_MANAGE,
    )
    assert not decision.allowed
    assert decision.reason is AuthorizationReason.MEMBERSHIP_INACTIVE


def test_missing_or_wrong_membership_is_denied_without_role_inference() -> None:
    assert not authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=None,
        action=VwsAction.VWS_VIEW,
    ).allowed
    decision = authorize_vws_action(
        actor_user_id="user-2",
        risk_workspace_id="vws-1",
        membership=make_membership(MembershipRole.OWNER, user_id="user-1"),
        action=VwsAction.VWS_VIEW,
    )
    assert decision.reason is AuthorizationReason.NOT_MEMBER


def test_source_manager_only_manages_own_mount() -> None:
    membership = make_membership(MembershipRole.SOURCE_MANAGER)
    own = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_RENAME,
        mount=make_mount(owner="user-1"),
    )
    other = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_RENAME,
        mount=make_mount(owner="user-2"),
    )
    assert own.allowed
    assert other.reason is AuthorizationReason.MOUNT_OWNERSHIP_REQUIRED


def test_owner_can_administer_but_cannot_operate_another_users_mount() -> None:
    membership = make_membership(MembershipRole.OWNER)
    other_mount = make_mount(owner="user-2")
    disable = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_DISABLE,
        mount=other_mount,
    )
    scope = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_SCOPE_MANAGE,
        mount=other_mount,
    )
    assert disable.allowed
    assert scope.reason is AuthorizationReason.MOUNT_OWNERSHIP_REQUIRED


def test_provider_authority_is_required_and_mismatch_is_denied() -> None:
    membership = make_membership(MembershipRole.SOURCE_MANAGER)
    mount = make_mount(owner="user-1")
    control_only = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_RECONNECT,
        mount=mount,
    )
    mismatch = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_RECONNECT,
        mount=mount,
        provider_credential_owner_user_id="user-2",
    )
    matching = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_RECONNECT,
        mount=mount,
        provider_credential_owner_user_id="user-1",
    )
    assert control_only.allowed and control_only.provider_authority_required
    assert mismatch.reason is AuthorizationReason.PROVIDER_AUTHORITY_MISMATCH
    assert matching.allowed and matching.provider_authority_required


def test_mount_from_another_workspace_is_denied() -> None:
    membership = make_membership(MembershipRole.OWNER)
    decision = authorize_vws_action(
        actor_user_id="user-1",
        risk_workspace_id="vws-1",
        membership=membership,
        action=VwsAction.MOUNT_DISABLE,
        mount=make_mount(vws_id="vws-2"),
    )
    assert decision.reason is AuthorizationReason.MOUNT_WORKSPACE_MISMATCH
