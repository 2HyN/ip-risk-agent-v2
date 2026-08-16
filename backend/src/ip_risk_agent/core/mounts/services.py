"""Pure Mount metadata mutation plans."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ip_risk_agent.core.audit import AuditEvent, AuditEventType
from ip_risk_agent.core.common import ActorType, DomainInvariantError, normalize_utc
from ip_risk_agent.core.memberships.authorization import (
    VwsAction,
    authorize_vws_action,
    require_authorized,
)
from ip_risk_agent.core.memberships.models import Membership

from .models import MountStatus, WorkspaceMount


@dataclass(frozen=True, slots=True)
class MountMutationPlan:
    mount: WorkspaceMount
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class MountRemovalPlan:
    mount_id: str
    audit_event: AuditEvent


def plan_mount_rename(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    mount: WorkspaceMount,
    new_alias: str,
    occurred_at: datetime,
    audit_event_id: str,
) -> MountMutationPlan:
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=actor_membership.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MOUNT_RENAME,
            mount=mount,
        )
    )
    occurred_at = normalize_utc(occurred_at, "mount_rename.occurred_at")
    updated = replace(mount, alias=new_alias, updated_at=occurred_at)
    if updated.alias == mount.alias:
        raise DomainInvariantError("mount already has the requested alias")
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=mount.risk_workspace_id,
        event_type=AuditEventType.MOUNT_RENAMED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={
            "mount_id": mount.id,
            "previous_alias": mount.alias,
            "new_alias": updated.alias,
        },
    )
    return MountMutationPlan(updated, audit_event)


def plan_mount_disable(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    mount: WorkspaceMount,
    occurred_at: datetime,
    audit_event_id: str,
) -> MountMutationPlan:
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=actor_membership.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MOUNT_DISABLE,
            mount=mount,
        )
    )
    if mount.status is MountStatus.DISABLED:
        raise DomainInvariantError("mount is already disabled")
    occurred_at = normalize_utc(occurred_at, "mount_disable.occurred_at")
    updated = replace(mount, status=MountStatus.DISABLED, updated_at=occurred_at)
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=mount.risk_workspace_id,
        event_type=AuditEventType.MOUNT_DISABLED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={"mount_id": mount.id},
    )
    return MountMutationPlan(updated, audit_event)


def plan_mount_removal(
    *,
    actor_user_id: str,
    actor_membership: Membership,
    mount: WorkspaceMount,
    occurred_at: datetime,
    audit_event_id: str,
) -> MountRemovalPlan:
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=actor_membership.risk_workspace_id,
            membership=actor_membership,
            action=VwsAction.MOUNT_REMOVE,
            mount=mount,
        )
    )
    occurred_at = normalize_utc(occurred_at, "mount_removal.occurred_at")
    audit_event = AuditEvent(
        id=audit_event_id,
        risk_workspace_id=mount.risk_workspace_id,
        event_type=AuditEventType.MOUNT_REMOVED,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        metadata_safe={"mount_id": mount.id},
    )
    return MountRemovalPlan(mount.id, audit_event)
