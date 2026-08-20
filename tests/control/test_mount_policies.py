from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ip_risk_agent.core.memberships import (
    AuthorizationDeniedError,
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    WorkspaceMount,
    plan_mount_disable,
    plan_mount_removal,
    plan_mount_rename,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


def membership(user_id: str, role: MembershipRole) -> Membership:
    return Membership(
        id=membership_id_for("vws-1", user_id),
        risk_workspace_id="vws-1",
        user_id=user_id,
        role=role,
        status=MembershipStatus.ACTIVE,
        invited_by="owner-1",
        created_at=NOW,
        updated_at=NOW,
    )


def mount(owner: str = "manager-1") -> WorkspaceMount:
    return WorkspaceMount(
        id="mount-1",
        risk_workspace_id="vws-1",
        source_workspace_id="source-workspace-1",
        alias="backend",
        mounted_by_user_id=owner,
        source_connection_id="connection-1",
        status=MountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def test_source_manager_can_rename_own_mount_without_changing_identity() -> None:
    plan = plan_mount_rename(
        actor_user_id="manager-1",
        actor_membership=membership("manager-1", MembershipRole.SOURCE_MANAGER),
        mount=mount(),
        new_alias="server",
        occurred_at=LATER,
        audit_event_id="audit-1",
    )
    assert plan.mount.id == "mount-1"
    assert plan.mount.source_workspace_id == "source-workspace-1"
    assert plan.mount.alias == "server"


def test_owner_cannot_rename_another_users_mount() -> None:
    with pytest.raises(AuthorizationDeniedError):
        plan_mount_rename(
            actor_user_id="owner-1",
            actor_membership=membership("owner-1", MembershipRole.OWNER),
            mount=mount(owner="manager-1"),
            new_alias="server",
            occurred_at=LATER,
            audit_event_id="audit-1",
        )


def test_owner_can_disable_and_remove_another_users_mount() -> None:
    owner = membership("owner-1", MembershipRole.OWNER)
    other_mount = mount(owner="manager-1")
    disabled = plan_mount_disable(
        actor_user_id="owner-1",
        actor_membership=owner,
        mount=other_mount,
        occurred_at=LATER,
        audit_event_id="audit-1",
    )
    removed = plan_mount_removal(
        actor_user_id="owner-1",
        actor_membership=owner,
        mount=other_mount,
        occurred_at=LATER,
        audit_event_id="audit-2",
    )
    assert disabled.mount.status is MountStatus.DISABLED
    assert removed.mount_id == other_mount.id


def test_source_manager_cannot_administratively_disable_mount() -> None:
    with pytest.raises(AuthorizationDeniedError):
        plan_mount_disable(
            actor_user_id="manager-1",
            actor_membership=membership("manager-1", MembershipRole.SOURCE_MANAGER),
            mount=mount(owner="manager-1"),
            occurred_at=LATER,
            audit_event_id="audit-1",
        )
