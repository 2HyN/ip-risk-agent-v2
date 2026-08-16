from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ip_risk_agent.core.common import DomainInvariantError
from ip_risk_agent.core.memberships import (
    AuthorizationDeniedError,
    Membership,
    MembershipRole,
    MembershipStatus,
    invitation_id_for,
    membership_id_for,
)
from ip_risk_agent.core.mounts import MountStatus, WorkspaceMount
from ip_risk_agent.core.notifications import NotificationType
from ip_risk_agent.core.workspaces import (
    RiskWorkspace,
    RiskWorkspaceStatus,
    plan_invitation_acceptance,
    plan_invitation_revocation,
    plan_member_removal,
    plan_membership_invitation,
    plan_ownership_transfer,
    plan_role_change,
    plan_workspace_creation,
    plan_workspace_deletion,
)

NOW = datetime(2026, 8, 16, 11, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


def make_membership(user_id: str, role: MembershipRole) -> Membership:
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


def make_workspace() -> RiskWorkspace:
    return RiskWorkspace(
        id="vws-1",
        name="Project Aurora",
        owner_user_id="owner-1",
        security_policy_version="security-v1",
        retention_policy_version="retention-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def make_mount(mount_id: str, owner: str, status: MountStatus = MountStatus.ACTIVE) -> WorkspaceMount:
    return WorkspaceMount(
        id=mount_id,
        risk_workspace_id="vws-1",
        source_workspace_id=f"source-{mount_id}",
        alias=mount_id,
        mounted_by_user_id=owner,
        source_connection_id=f"connection-{mount_id}",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def test_workspace_creation_always_creates_canonical_owner_membership() -> None:
    plan = plan_workspace_creation(
        workspace_id="vws-1",
        owner_user_id="owner-1",
        name="Project Aurora",
        security_policy_version="security-v1",
        retention_policy_version="retention-v1",
        occurred_at=NOW,
        audit_event_id="audit-1",
    )
    assert plan.workspace.owner_user_id == "owner-1"
    assert plan.owner_membership.role is MembershipRole.OWNER
    assert plan.owner_membership.status is MembershipStatus.ACTIVE
    assert plan.owner_membership.id == membership_id_for("vws-1", "owner-1")


def test_invitation_is_email_normalized_idempotent_and_cannot_assign_owner() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    first = plan_membership_invitation(
        actor_user_id="owner-1",
        actor_membership=owner,
        email=" Reviewer@Example.COM ",
        role=MembershipRole.RISK_REVIEWER,
        occurred_at=NOW,
        expires_at=NOW + timedelta(days=7),
        audit_event_id="audit-1",
    )
    assert first.invitation.email == "reviewer@example.com"
    assert first.invitation.id == invitation_id_for("vws-1", "reviewer@example.com")

    with pytest.raises(DomainInvariantError, match="ownership transfer"):
        plan_membership_invitation(
            actor_user_id="owner-1",
            actor_membership=owner,
            email="other@example.com",
            role=MembershipRole.OWNER,
            occurred_at=NOW,
            audit_event_id="audit-2",
        )


def test_source_manager_cannot_invite_members() -> None:
    manager = make_membership("manager-1", MembershipRole.SOURCE_MANAGER)
    with pytest.raises(AuthorizationDeniedError):
        plan_membership_invitation(
            actor_user_id="manager-1",
            actor_membership=manager,
            email="viewer@example.com",
            role=MembershipRole.VIEWER,
            occurred_at=NOW,
            audit_event_id="audit-1",
        )


def test_verified_invitee_can_accept_pending_invitation() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    invitation = plan_membership_invitation(
        actor_user_id="owner-1",
        actor_membership=owner,
        email="reviewer@example.com",
        role=MembershipRole.RISK_REVIEWER,
        occurred_at=NOW,
        expires_at=NOW + timedelta(days=7),
        audit_event_id="audit-invite",
    ).invitation
    accepted = plan_invitation_acceptance(
        authenticated_user_id="reviewer-1",
        verified_email="Reviewer@Example.com",
        invitation=invitation,
        occurred_at=LATER,
        audit_event_id="audit-accept",
    )
    assert accepted.invitation.status.value == "ACCEPTED"
    assert accepted.membership.user_id == "reviewer-1"
    assert accepted.membership.role is MembershipRole.RISK_REVIEWER
    assert accepted.membership.status is MembershipStatus.ACTIVE


def test_invitation_acceptance_rejects_email_mismatch_and_expiry() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    invitation = plan_membership_invitation(
        actor_user_id="owner-1",
        actor_membership=owner,
        email="reviewer@example.com",
        role=MembershipRole.RISK_REVIEWER,
        occurred_at=NOW,
        expires_at=LATER,
        audit_event_id="audit-invite",
    ).invitation
    with pytest.raises(DomainInvariantError, match="does not match"):
        plan_invitation_acceptance(
            authenticated_user_id="reviewer-1",
            verified_email="other@example.com",
            invitation=invitation,
            occurred_at=NOW,
            audit_event_id="audit-accept",
        )
    with pytest.raises(DomainInvariantError, match="expired"):
        plan_invitation_acceptance(
            authenticated_user_id="reviewer-1",
            verified_email="reviewer@example.com",
            invitation=invitation,
            occurred_at=LATER,
            audit_event_id="audit-accept",
        )


def test_owner_can_revoke_pending_invitation() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    invitation = plan_membership_invitation(
        actor_user_id="owner-1",
        actor_membership=owner,
        email="viewer@example.com",
        role=MembershipRole.VIEWER,
        occurred_at=NOW,
        audit_event_id="audit-invite",
    ).invitation
    revoked = plan_invitation_revocation(
        actor_user_id="owner-1",
        actor_membership=owner,
        invitation=invitation,
        occurred_at=LATER,
        audit_event_id="audit-revoke",
    )
    assert revoked.invitation.status.value == "REVOKED"


def test_role_change_cannot_bypass_ownership_transfer() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    reviewer = make_membership("reviewer-1", MembershipRole.RISK_REVIEWER)
    plan = plan_role_change(
        actor_user_id="owner-1",
        actor_membership=owner,
        target_membership=reviewer,
        new_role=MembershipRole.SOURCE_MANAGER,
        occurred_at=LATER,
        audit_event_id="audit-1",
    )
    assert plan.membership.role is MembershipRole.SOURCE_MANAGER
    assert plan.mounts == ()

    with pytest.raises(DomainInvariantError, match="ownership transfer"):
        plan_role_change(
            actor_user_id="owner-1",
            actor_membership=owner,
            target_membership=reviewer,
            new_role=MembershipRole.OWNER,
            occurred_at=LATER,
            audit_event_id="audit-2",
        )


def test_source_manager_demotion_preserves_mount_and_requires_owner_action() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    manager = make_membership("manager-1", MembershipRole.SOURCE_MANAGER)
    plan = plan_role_change(
        actor_user_id="owner-1",
        actor_membership=owner,
        target_membership=manager,
        new_role=MembershipRole.RISK_REVIEWER,
        occurred_at=LATER,
        audit_event_id="audit-1",
        candidate_mounts=(make_mount("backend", "manager-1"),),
        owner_user_id="owner-1",
        notification_id="notification-1",
    )
    assert plan.membership.role is MembershipRole.RISK_REVIEWER
    assert plan.mounts[0].status is MountStatus.MANAGER_ACTION_REQUIRED
    assert plan.notification is not None


def test_ownership_transfer_updates_workspace_and_both_memberships() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    target = make_membership("reviewer-1", MembershipRole.RISK_REVIEWER)
    plan = plan_ownership_transfer(
        actor_user_id="owner-1",
        workspace=make_workspace(),
        previous_owner_membership=owner,
        new_owner_membership=target,
        previous_owner_new_role=MembershipRole.SOURCE_MANAGER,
        occurred_at=LATER,
        audit_event_id="audit-1",
    )
    assert plan.workspace.owner_user_id == "reviewer-1"
    assert plan.previous_owner_membership.role is MembershipRole.SOURCE_MANAGER
    assert plan.new_owner_membership.role is MembershipRole.OWNER


def test_member_removal_preserves_mounts_and_requires_owner_action() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    target = make_membership("manager-1", MembershipRole.SOURCE_MANAGER)
    active = make_mount("active", "manager-1")
    disabled = make_mount("disabled", "manager-1", MountStatus.DISABLED)
    other = make_mount("other", "someone-else")
    plan = plan_member_removal(
        actor_user_id="owner-1",
        actor_membership=owner,
        target_membership=target,
        candidate_mounts=(active, disabled, other),
        owner_user_id="owner-1",
        occurred_at=LATER,
        audit_event_id="audit-1",
        notification_id="notification-1",
    )
    assert plan.membership.status is MembershipStatus.REMOVED
    assert len(plan.mounts) == 1
    assert plan.mounts[0].id == active.id
    assert plan.mounts[0].status is MountStatus.MANAGER_ACTION_REQUIRED
    assert plan.notification is not None
    assert plan.notification.notification_type is NotificationType.MOUNT_MANAGER_ACTION_REQUIRED


def test_owner_cannot_be_removed_before_transfer() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    with pytest.raises(DomainInvariantError, match="cannot be removed"):
        plan_member_removal(
            actor_user_id="owner-1",
            actor_membership=owner,
            target_membership=owner,
            candidate_mounts=(),
            owner_user_id="owner-1",
            occurred_at=LATER,
            audit_event_id="audit-1",
            notification_id=None,
        )


def test_workspace_deletion_requires_canonical_owner_and_marks_deleting() -> None:
    owner = make_membership("owner-1", MembershipRole.OWNER)
    plan = plan_workspace_deletion(
        actor_user_id="owner-1",
        actor_membership=owner,
        workspace=make_workspace(),
        occurred_at=LATER,
        audit_event_id="audit-1",
    )
    assert plan.workspace.status is RiskWorkspaceStatus.DELETING
