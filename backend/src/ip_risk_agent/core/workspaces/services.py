"""Pure workspace and membership mutation plans for transactional application."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ip_risk_agent.core.audit import AuditEvent, AuditEventType
from ip_risk_agent.core.common import ActorType, DomainInvariantError, normalize_utc, require_non_empty
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    Membership,
    MembershipInvitation,
    MembershipRole,
    MembershipStatus,
    VwsAction,
    authorize_vws_action,
    invitation_id_for,
    membership_id_for,
    normalize_invitation_email,
    require_authorized,
)
from ip_risk_agent.core.mounts import MountStatus, WorkspaceMount
from ip_risk_agent.core.notifications import Notification, NotificationStatus, NotificationType

from .models import RiskWorkspace, RiskWorkspaceStatus


@dataclass(frozen=True, slots=True)
class WorkspaceCreationPlan:
    workspace: RiskWorkspace
    owner_membership: Membership
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class InvitationPlan:
    invitation: MembershipInvitation
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class InvitationAcceptancePlan:
    invitation: MembershipInvitation
    membership: Membership
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class InvitationRevocationPlan:
    invitation: MembershipInvitation
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class RoleChangePlan:
    membership: Membership
    mounts: tuple[WorkspaceMount, ...]
    notification: Notification | None
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class OwnershipTransferPlan:
    workspace: RiskWorkspace
    previous_owner_membership: Membership
    new_owner_membership: Membership
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class MemberRemovalPlan:
    membership: Membership
    mounts: tuple[WorkspaceMount, ...]
    notification: Notification | None
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class WorkspaceDeletionPlan:
    workspace: RiskWorkspace
    audit_event: AuditEvent


def plan_workspace_creation(
    *,
    workspace_id: str,
    owner_user_id: str,
    name: str,
    security_policy_version: str,
    retention_policy_version: str,
    occurred_at: datetime,
    audit_event_id: str,
    description: str | None = None,
) -> WorkspaceCreationPlan:
    occurred_at = normalize_utc(occurred_at, "workspace_creation.occurred_at")
    workspace = RiskWorkspace(
        id=workspace_id,
        name=name,
        owner_user_id=owner_user_id,
        security_policy_version=security_policy_version,
        retention_policy_version=retention_policy_version,
        created_at=occurred_at,
        updated_at=occurred_at,
        description=description,
    )
    owner_membership = Membership(
        id=membership_id_for(workspace.id, owner_user_id),
        risk_workspace_id=workspace.id,
        user_id=owner_user_id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE,
        invited_by=owner_user_id,
        created_at=occurred_at,
        updated_at=occurred_at,
    )
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=workspace.id,
        event_type=AuditEventType.WORKSPACE_CREATED,
        actor_type=ActorType.USER,
        actor_user_id=owner_user_id,
        occurred_at=occurred_at,
        metadata_safe={"workspace_name": workspace.name},
    )
    return WorkspaceCreationPlan(workspace, owner_membership, audit_event)


def plan_membership_invitation(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    email: str,
    role: MembershipRole,
    occurred_at: datetime,
    audit_event_id: str,
    expires_at: datetime | None = None,
) -> InvitationPlan:
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=actor_membership.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MEMBER_MANAGE,
        )
    )
    if role is MembershipRole.OWNER:
        raise DomainInvariantError("OWNER must be assigned through ownership transfer")
    normalized_email = normalize_invitation_email(email)
    occurred_at = normalize_utc(occurred_at, "membership_invitation.occurred_at")
    invitation = MembershipInvitation(
        id=invitation_id_for(actor_membership.risk_workspace_id, normalized_email),
        risk_workspace_id=actor_membership.risk_workspace_id,
        email=normalized_email,
        role=role,
        status=InvitationStatus.PENDING,
        invited_by=actor_user_id,
        created_at=occurred_at,
        updated_at=occurred_at,
        expires_at=expires_at,
    )
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=actor_membership.risk_workspace_id,
        event_type=AuditEventType.MEMBER_INVITED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={"invitation_id": invitation.id, "role": role.value},
    )
    return InvitationPlan(invitation, audit_event)


def plan_invitation_acceptance(
    *,
    authenticated_user_id: str,
    verified_email: str,
    invitation: MembershipInvitation,
    occurred_at: datetime,
    audit_event_id: str,
) -> InvitationAcceptancePlan:
    """Convert a pending invitation after the OIDC layer verifies the email."""

    authenticated_user_id = require_non_empty(authenticated_user_id, "authenticated_user_id")
    occurred_at = normalize_utc(occurred_at, "invitation_acceptance.occurred_at")
    if invitation.status is not InvitationStatus.PENDING:
        raise DomainInvariantError("only a pending invitation may be accepted")
    if invitation.email != normalize_invitation_email(verified_email):
        raise DomainInvariantError("verified email does not match the invitation")
    if invitation.expires_at is not None and occurred_at >= invitation.expires_at:
        raise DomainInvariantError("invitation has expired")
    accepted_invitation = replace(
        invitation,
        status=InvitationStatus.ACCEPTED,
        updated_at=occurred_at,
    )
    membership = Membership(
        id=membership_id_for(invitation.risk_workspace_id, authenticated_user_id),
        risk_workspace_id=invitation.risk_workspace_id,
        user_id=authenticated_user_id,
        role=invitation.role,
        status=MembershipStatus.ACTIVE,
        invited_by=invitation.invited_by,
        created_at=occurred_at,
        updated_at=occurred_at,
    )
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=invitation.risk_workspace_id,
        event_type=AuditEventType.MEMBER_INVITATION_ACCEPTED,
        actor_type=ActorType.USER,
        actor_user_id=authenticated_user_id,
        occurred_at=occurred_at,
        metadata_safe={
            "invitation_id": invitation.id,
            "membership_id": membership.id,
            "role": membership.role.value,
        },
    )
    return InvitationAcceptancePlan(accepted_invitation, membership, audit_event)


def plan_invitation_revocation(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    invitation: MembershipInvitation,
    occurred_at: datetime,
    audit_event_id: str,
) -> InvitationRevocationPlan:
    if actor_membership.risk_workspace_id != invitation.risk_workspace_id:
        raise DomainInvariantError("membership and invitation must belong to the same VWS")
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=invitation.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MEMBER_MANAGE,
        )
    )
    if invitation.status is not InvitationStatus.PENDING:
        raise DomainInvariantError("only a pending invitation may be revoked")
    occurred_at = normalize_utc(occurred_at, "invitation_revocation.occurred_at")
    revoked = replace(invitation, status=InvitationStatus.REVOKED, updated_at=occurred_at)
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=invitation.risk_workspace_id,
        event_type=AuditEventType.MEMBER_INVITATION_REVOKED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={"invitation_id": invitation.id},
    )
    return InvitationRevocationPlan(revoked, audit_event)


def plan_role_change(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    target_membership: Membership,
    new_role: MembershipRole,
    occurred_at: datetime,
    audit_event_id: str,
    candidate_mounts: tuple[WorkspaceMount, ...] = (),
    owner_user_id: str | None = None,
    notification_id: str | None = None,
) -> RoleChangePlan:
    _require_same_workspace(actor_membership, target_membership)
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=actor_membership.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MEMBER_MANAGE,
        )
    )
    if target_membership.role is MembershipRole.OWNER or new_role is MembershipRole.OWNER:
        raise DomainInvariantError("OWNER changes require ownership transfer")
    if target_membership.status is not MembershipStatus.ACTIVE:
        raise DomainInvariantError("only active memberships may change role")
    if target_membership.role is new_role:
        raise DomainInvariantError("membership already has the requested role")
    if any(mount.risk_workspace_id != target_membership.risk_workspace_id for mount in candidate_mounts):
        raise DomainInvariantError("candidate mounts must belong to the target VWS")
    occurred_at = normalize_utc(occurred_at, "role_change.occurred_at")
    updated = replace(target_membership, role=new_role, updated_at=occurred_at)
    affected_mounts: tuple[WorkspaceMount, ...] = ()
    notification = None
    if (
        target_membership.role is MembershipRole.SOURCE_MANAGER
        and new_role is not MembershipRole.SOURCE_MANAGER
    ):
        affected_mounts = _manager_action_mounts(
            candidate_mounts,
            custodian_user_id=target_membership.user_id,
            occurred_at=occurred_at,
        )
        if affected_mounts:
            notification = _manager_action_notification(
                notification_id=notification_id,
                owner_user_id=owner_user_id,
                risk_workspace_id=target_membership.risk_workspace_id,
                affected_mounts=affected_mounts,
                affected_user_id=target_membership.user_id,
                occurred_at=occurred_at,
            )
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=target_membership.risk_workspace_id,
        event_type=AuditEventType.MEMBER_ROLE_CHANGED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={
            "target_user_id": target_membership.user_id,
            "previous_role": target_membership.role.value,
            "new_role": new_role.value,
            "affected_mount_ids": [mount.id for mount in affected_mounts],
        },
    )
    return RoleChangePlan(updated, affected_mounts, notification, audit_event)


def plan_ownership_transfer(
    *,
    actor_user_id: str,
    workspace: RiskWorkspace,
    previous_owner_membership: Membership,
    new_owner_membership: Membership,
    previous_owner_new_role: MembershipRole,
    occurred_at: datetime,
    audit_event_id: str,
) -> OwnershipTransferPlan:
    _require_same_workspace(previous_owner_membership, new_owner_membership)
    if workspace.id != previous_owner_membership.risk_workspace_id:
        raise DomainInvariantError("workspace and memberships must belong to the same VWS")
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=workspace.id,
            membership=previous_owner_membership,
            action=VwsAction.OWNERSHIP_TRANSFER,
        )
    )
    if workspace.owner_user_id != actor_user_id or previous_owner_membership.role is not MembershipRole.OWNER:
        raise DomainInvariantError("only the canonical current owner may transfer ownership")
    if new_owner_membership.user_id == actor_user_id:
        raise DomainInvariantError("ownership target must be another user")
    if new_owner_membership.status is not MembershipStatus.ACTIVE:
        raise DomainInvariantError("ownership target must be an active member")
    if previous_owner_new_role is not MembershipRole.SOURCE_MANAGER:
        raise DomainInvariantError("previous owner must become SOURCE_MANAGER in MVP")
    occurred_at = normalize_utc(occurred_at, "ownership_transfer.occurred_at")
    updated_workspace = replace(
        workspace,
        owner_user_id=new_owner_membership.user_id,
        updated_at=occurred_at,
    )
    updated_previous_owner = replace(
        previous_owner_membership,
        role=previous_owner_new_role,
        updated_at=occurred_at,
    )
    updated_new_owner = replace(
        new_owner_membership,
        role=MembershipRole.OWNER,
        updated_at=occurred_at,
    )
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=workspace.id,
        event_type=AuditEventType.OWNERSHIP_TRANSFERRED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={
            "previous_owner_user_id": actor_user_id,
            "new_owner_user_id": new_owner_membership.user_id,
            "previous_owner_new_role": previous_owner_new_role.value,
        },
    )
    return OwnershipTransferPlan(
        updated_workspace,
        updated_previous_owner,
        updated_new_owner,
        audit_event,
    )


def plan_member_removal(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    target_membership: Membership,
    candidate_mounts: tuple[WorkspaceMount, ...],
    owner_user_id: str,
    occurred_at: datetime,
    audit_event_id: str,
    notification_id: str | None,
) -> MemberRemovalPlan:
    _require_same_workspace(actor_membership, target_membership)
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=actor_membership.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MEMBER_MANAGE,
        )
    )
    if target_membership.role is MembershipRole.OWNER or target_membership.user_id == owner_user_id:
        raise DomainInvariantError("workspace owner cannot be removed before ownership transfer")
    if target_membership.status is MembershipStatus.REMOVED:
        raise DomainInvariantError("membership is already removed")
    if any(mount.risk_workspace_id != target_membership.risk_workspace_id for mount in candidate_mounts):
        raise DomainInvariantError("candidate mounts must belong to the target VWS")

    occurred_at = normalize_utc(occurred_at, "member_removal.occurred_at")
    updated_membership = replace(
        target_membership,
        status=MembershipStatus.REMOVED,
        updated_at=occurred_at,
    )
    affected_mounts = _manager_action_mounts(
        candidate_mounts,
        custodian_user_id=target_membership.user_id,
        occurred_at=occurred_at,
    )
    notification = None
    if affected_mounts:
        notification = _manager_action_notification(
            notification_id=notification_id,
            owner_user_id=owner_user_id,
            risk_workspace_id=target_membership.risk_workspace_id,
            affected_mounts=affected_mounts,
            affected_user_id=target_membership.user_id,
            occurred_at=occurred_at,
        )
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=target_membership.risk_workspace_id,
        event_type=AuditEventType.MEMBER_REMOVED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={
            "target_user_id": target_membership.user_id,
            "affected_mount_ids": [mount.id for mount in affected_mounts],
        },
    )
    return MemberRemovalPlan(updated_membership, affected_mounts, notification, audit_event)


def plan_workspace_deletion(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    workspace: RiskWorkspace,
    occurred_at: datetime,
    audit_event_id: str,
) -> WorkspaceDeletionPlan:
    if workspace.id != actor_membership.risk_workspace_id:
        raise DomainInvariantError("workspace and membership must belong to the same VWS")
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=workspace.id,
            membership=actor_membership,
            action=VwsAction.WORKSPACE_DELETE,
        )
    )
    if workspace.owner_user_id != actor_user_id:
        raise DomainInvariantError("only the canonical owner may delete a workspace")
    if workspace.status is not RiskWorkspaceStatus.ACTIVE:
        raise DomainInvariantError("only an active workspace may be deleted")
    occurred_at = normalize_utc(occurred_at, "workspace_deletion.occurred_at")
    updated = replace(workspace, status=RiskWorkspaceStatus.DELETING, updated_at=occurred_at)
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=workspace.id,
        event_type=AuditEventType.WORKSPACE_DELETION_REQUESTED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
    )
    return WorkspaceDeletionPlan(updated, audit_event)


def _require_same_workspace(first: Membership, second: Membership) -> None:
    if first.risk_workspace_id != second.risk_workspace_id:
        raise DomainInvariantError("memberships must belong to the same VWS")


def _manager_action_mounts(
    candidate_mounts: tuple[WorkspaceMount, ...],
    *,
    custodian_user_id: str,
    occurred_at: datetime,
) -> tuple[WorkspaceMount, ...]:
    return tuple(
        replace(mount, status=MountStatus.MANAGER_ACTION_REQUIRED, updated_at=occurred_at)
        for mount in candidate_mounts
        if mount.mounted_by_user_id == custodian_user_id
        and mount.status is not MountStatus.DISABLED
    )


def _manager_action_notification(
    *,
    notification_id: str | None,
    owner_user_id: str | None,
    risk_workspace_id: str,
    affected_mounts: tuple[WorkspaceMount, ...],
    affected_user_id: str,
    occurred_at: datetime,
) -> Notification:
    return Notification(
        id=require_non_empty(notification_id or "", "manager_action.notification_id"),
        user_id=require_non_empty(owner_user_id or "", "manager_action.owner_user_id"),
        risk_workspace_id=risk_workspace_id,
        notification_type=NotificationType.MOUNT_MANAGER_ACTION_REQUIRED,
        status=NotificationStatus.UNREAD,
        created_at=occurred_at,
        metadata_safe={
            "affected_user_id": affected_user_id,
            "mount_ids": [mount.id for mount in affected_mounts],
        },
    )
