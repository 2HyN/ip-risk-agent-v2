"""Apply pure workspace/mount plans through one Control Unit of Work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from ip_risk_agent.application.repositories import (
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.audit import AuditEvent, AuditEventType
from ip_risk_agent.core.risk import (
    RiskEvent,
    RiskEventType,
    RiskLifecycleState,
    risk_event_id_for,
)
from ip_risk_agent.core.common import ActorType, DomainInvariantError, normalize_utc
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    VwsAction,
    authorize_vws_action,
    require_authorized,
)
from ip_risk_agent.core.mounts import (
    MountMutationPlan,
    MountRemovalPlan,
    WorkspaceMount,
    plan_mount_disable,
    plan_mount_removal,
    plan_mount_rename,
)
from ip_risk_agent.core.workspaces import (
    InvitationAcceptancePlan,
    InvitationPlan,
    InvitationRevocationPlan,
    MemberRemovalPlan,
    OwnershipTransferPlan,
    RoleChangePlan,
    WorkspaceCreationPlan,
    WorkspaceDeletionPlan,
    plan_invitation_acceptance,
    plan_invitation_revocation,
    plan_member_removal,
    plan_membership_invitation,
    plan_ownership_transfer,
    plan_role_change,
    plan_workspace_creation,
    plan_workspace_deletion,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


class WorkspaceUpdateConflictError(DomainInvariantError):
    pass


class WorkspaceAdministrationService:
    """Transaction boundary for Phase 2 workspace and mount mutation plans."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
        id_factory: IdFactory,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory

    async def create_workspace(
        self,
        *,
        owner_user_id: str,
        name: str,
        security_policy_version: str,
        retention_policy_version: str,
        description: str | None = None,
    ) -> WorkspaceCreationPlan:
        occurred_at = self._clock()
        plan = plan_workspace_creation(
            workspace_id=self._id_factory("workspace"),
            owner_user_id=owner_user_id,
            name=name,
            security_policy_version=security_policy_version,
            retention_policy_version=retention_policy_version,
            occurred_at=occurred_at,
            audit_event_id=self._id_factory("audit"),
            description=description,
        )
        async with self._unit_of_work_factory() as uow:
            await _require_user(uow, owner_user_id)
            await uow.workspaces.add(plan.workspace)
            await uow.memberships.add(plan.owner_membership)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def invite_member(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        email: str,
        role: MembershipRole,
        expires_at: datetime | None = None,
    ) -> InvitationPlan:
        async with self._unit_of_work_factory() as uow:
            actor = await _require_membership(uow, risk_workspace_id, actor_user_id)
            plan = plan_membership_invitation(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                email=email,
                role=role,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
                expires_at=expires_at,
            )
            await uow.memberships.add_invitation(plan.invitation)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def accept_invitation(
        self,
        *,
        invitation_id: str,
        authenticated_user_id: str,
        verified_email: str,
    ) -> InvitationAcceptancePlan:
        async with self._unit_of_work_factory() as uow:
            await _require_user(uow, authenticated_user_id)
            invitation = await uow.memberships.get_invitation(invitation_id)
            if invitation is None:
                raise RecordNotFoundError(f"membership invitation was not found: {invitation_id!r}")
            plan = plan_invitation_acceptance(
                authenticated_user_id=authenticated_user_id,
                verified_email=verified_email,
                invitation=invitation,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.memberships.save_invitation(plan.invitation)
            await uow.memberships.add(plan.membership)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def revoke_invitation(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        invitation_id: str,
    ) -> InvitationRevocationPlan:
        async with self._unit_of_work_factory() as uow:
            actor = await _require_membership(uow, risk_workspace_id, actor_user_id)
            invitation = await uow.memberships.get_invitation(invitation_id)
            if invitation is None:
                raise RecordNotFoundError(f"membership invitation was not found: {invitation_id!r}")
            plan = plan_invitation_revocation(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                invitation=invitation,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.memberships.save_invitation(plan.invitation)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def change_member_role(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
        new_role: MembershipRole,
    ) -> RoleChangePlan:
        async with self._unit_of_work_factory() as uow:
            actor = await _require_membership(uow, risk_workspace_id, actor_user_id)
            target = await _require_membership(uow, risk_workspace_id, target_user_id)
            workspace = await _require_workspace(uow, risk_workspace_id)
            candidate_mounts = await uow.mounts.list_by_custodian(
                risk_workspace_id, target_user_id
            )
            plan = plan_role_change(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                target_membership=target,
                new_role=new_role,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
                candidate_mounts=candidate_mounts,
                owner_user_id=workspace.owner_user_id,
                notification_id=self._id_factory("notification"),
            )
            await uow.memberships.save(plan.membership)
            for mount in plan.mounts:
                await uow.mounts.save(mount)
            if plan.notification is not None:
                await uow.notifications.add(plan.notification)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def transfer_ownership(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        new_owner_user_id: str,
    ) -> OwnershipTransferPlan:
        async with self._unit_of_work_factory() as uow:
            workspace = await _require_workspace(uow, risk_workspace_id)
            previous_owner = await _require_membership(uow, risk_workspace_id, actor_user_id)
            new_owner = await _require_membership(uow, risk_workspace_id, new_owner_user_id)
            plan = plan_ownership_transfer(
                actor_user_id=actor_user_id,
                workspace=workspace,
                previous_owner_membership=previous_owner,
                new_owner_membership=new_owner,
                previous_owner_new_role=MembershipRole.SOURCE_MANAGER,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.workspaces.save(plan.workspace)
            await uow.memberships.save(plan.previous_owner_membership)
            await uow.memberships.save(plan.new_owner_membership)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def remove_member(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
    ) -> MemberRemovalPlan:
        async with self._unit_of_work_factory() as uow:
            actor = await _require_membership(uow, risk_workspace_id, actor_user_id)
            target = await _require_membership(uow, risk_workspace_id, target_user_id)
            workspace = await _require_workspace(uow, risk_workspace_id)
            candidate_mounts = await uow.mounts.list_by_custodian(
                risk_workspace_id, target_user_id
            )
            plan = plan_member_removal(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                target_membership=target,
                candidate_mounts=candidate_mounts,
                owner_user_id=workspace.owner_user_id,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
                notification_id=self._id_factory("notification"),
            )
            await uow.memberships.save(plan.membership)
            for mount in plan.mounts:
                await uow.mounts.save(mount)
            if plan.notification is not None:
                await uow.notifications.add(plan.notification)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def request_workspace_deletion(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
    ) -> WorkspaceDeletionPlan:
        async with self._unit_of_work_factory() as uow:
            actor = await _require_membership(uow, risk_workspace_id, actor_user_id)
            workspace = await _require_workspace(uow, risk_workspace_id)
            plan = plan_workspace_deletion(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                workspace=workspace,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.workspaces.save(plan.workspace)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def update_workspace(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        expected_updated_at: datetime,
        name: str | None = None,
        description: str | None = None,
        description_provided: bool = False,
    ):
        expected_updated_at = normalize_utc(
            expected_updated_at,
            "workspace_update.expected_updated_at",
        )
        async with self._unit_of_work_factory() as uow:
            actor = await _require_membership(uow, risk_workspace_id, actor_user_id)
            require_authorized(
                authorize_vws_action(
                    actor_user_id=actor_user_id,
                    risk_workspace_id=risk_workspace_id,
                    membership=actor,
                    action=VwsAction.VWS_SECURITY_MANAGE,
                )
            )
            workspace = await _require_workspace(uow, risk_workspace_id)
            if workspace.updated_at != expected_updated_at:
                raise WorkspaceUpdateConflictError("workspace update version conflict")
            next_name = workspace.name if name is None else name
            next_description = (
                description if description_provided else workspace.description
            )
            if next_name == workspace.name and next_description == workspace.description:
                return workspace
            occurred_at = max(
                normalize_utc(self._clock(), "workspace_update.clock"),
                workspace.updated_at + timedelta(microseconds=1),
            )
            workspace = replace(
                workspace,
                name=next_name,
                description=next_description,
                updated_at=occurred_at,
            )
            await uow.workspaces.save(workspace)
            await uow.audit.append(
                AuditEvent(
                    id=self._id_factory("audit"),
                    risk_workspace_id=risk_workspace_id,
                    event_type=AuditEventType.WORKSPACE_UPDATED,
                    actor_type=ActorType.USER,
                    actor_user_id=actor_user_id,
                    occurred_at=occurred_at,
                    metadata_safe={"workspace_name": workspace.name},
                )
            )
            await uow.commit()
        return workspace

    async def rename_mount(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        mount_id: str,
        new_alias: str,
    ) -> MountMutationPlan:
        async with self._unit_of_work_factory() as uow:
            actor, mount = await _membership_and_mount(
                uow, risk_workspace_id, actor_user_id, mount_id
            )
            plan = plan_mount_rename(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                mount=mount,
                new_alias=new_alias,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.mounts.save(plan.mount)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def disable_mount(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        mount_id: str,
    ) -> MountMutationPlan:
        async with self._unit_of_work_factory() as uow:
            actor, mount = await _membership_and_mount(
                uow, risk_workspace_id, actor_user_id, mount_id
            )
            plan = plan_mount_disable(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                mount=mount,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.mounts.save(plan.mount)
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan

    async def remove_mount(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        mount_id: str,
    ) -> MountRemovalPlan:
        async with self._unit_of_work_factory() as uow:
            actor, mount = await _membership_and_mount(
                uow, risk_workspace_id, actor_user_id, mount_id
            )
            plan = plan_mount_removal(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                mount=mount,
                occurred_at=self._clock(),
                audit_event_id=self._id_factory("audit"),
            )
            await uow.mounts.remove(plan.mount_id)
            # 감시가 끝난 대상의 위험은 원장에서 지우지 않고 RESOLVED 로
            # 내린다. 지우면 "있었던 위험"의 기록이 사라지고, 그대로 두면
            # 감시하지도 않는 대상의 위험이 화면에 영원히 남는다. 같은
            # 대상을 다시 연결해 위험이 재확인되면 REOPENED 로 되살아난다.
            occurred_at = self._clock()
            for risk in await uow.risks.list_for_workspace(risk_workspace_id):
                if risk.lifecycle_state not in (
                    RiskLifecycleState.NEW,
                    RiskLifecycleState.EXISTING,
                ):
                    continue
                artifact = await uow.artifacts.get(risk.artifact_id)
                if artifact is None or artifact.mount_id != mount_id:
                    continue
                risk_time = max(occurred_at, risk.last_seen_at, risk.updated_at)
                updated = replace(
                    risk,
                    lifecycle_state=RiskLifecycleState.RESOLVED,
                    resolved_at=risk_time,
                    updated_at=risk_time,
                )
                await uow.risks.save(updated)
                await uow.risks.append_event(
                    RiskEvent(
                        id=risk_event_id_for(
                            risk.id,
                            f"mount-removed:{mount_id}",
                            RiskEventType.RESOLVED.value,
                        ),
                        risk_id=risk.id,
                        event_type=RiskEventType.RESOLVED,
                        actor_type=ActorType.USER,
                        actor_user_id=actor_user_id,
                        occurred_at=risk_time,
                        previous_state_safe={
                            "lifecycle_state": risk.lifecycle_state.value
                        },
                        new_state_safe={
                            "lifecycle_state": RiskLifecycleState.RESOLVED.value
                        },
                        analysis_job_id=risk.latest_analysis_job_id,
                        reason_safe="source mount removed",
                    )
                )
            await uow.audit.append(plan.audit_event)
            await uow.commit()
        return plan


async def _require_user(uow: ControlUnitOfWork, user_id: str) -> None:
    if await uow.users.get(user_id) is None:
        raise RecordNotFoundError(f"user was not found: {user_id!r}")


async def _require_workspace(uow: ControlUnitOfWork, workspace_id: str):
    workspace = await uow.workspaces.get(workspace_id)
    if workspace is None:
        raise RecordNotFoundError(f"workspace was not found: {workspace_id!r}")
    return workspace


async def _require_membership(
    uow: ControlUnitOfWork, workspace_id: str, user_id: str
) -> Membership:
    membership = await uow.memberships.get(workspace_id, user_id)
    if membership is None:
        raise RecordNotFoundError(
            f"membership was not found: workspace={workspace_id!r}, user={user_id!r}"
        )
    return membership


async def _membership_and_mount(
    uow: ControlUnitOfWork,
    workspace_id: str,
    user_id: str,
    mount_id: str,
) -> tuple[Membership, WorkspaceMount]:
    membership = await _require_membership(uow, workspace_id, user_id)
    mount = await uow.mounts.get(mount_id)
    if mount is None or mount.risk_workspace_id != workspace_id:
        raise RecordNotFoundError(
            f"mount was not found in workspace: workspace={workspace_id!r}, mount={mount_id!r}"
        )
    return membership, mount


__all__ = ["WorkspaceAdministrationService", "WorkspaceUpdateConflictError"]
