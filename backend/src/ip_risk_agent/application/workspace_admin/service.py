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
from ip_risk_agent.application.observability import CorrelationIds, StructuredLogger
from ip_risk_agent.application.risk_exclusion import exclude_mount_risks
from ip_risk_agent.application.workspace_purge import (
    WorkspaceDataEraser,
    merge_counts,
)
from ip_risk_agent.core.audit import AuditEvent, AuditEventType
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
        workspace_erasers: tuple[WorkspaceDataEraser, ...] = (),
        observer: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._workspace_erasers = workspace_erasers
        self._observer = observer or StructuredLogger()

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
        """workspace 를 지운다. 상태만 바꾸는 것이 아니라 **데이터를 없앤다.**

        두 걸음이다. 먼저 ``DELETING`` 으로 표시하고 감사 기록을 남긴 뒤, 등록된
        eraser 로 실제 데이터를 지운다. 나눈 이유는 되돌릴 수 없는 일이기 때문이다.
        지우다 실패하면 workspace 는 ``DELETING`` 으로 남고 다시 부르면 이어서
        마무리된다. eraser 는 같은 workspace 로 두 번 불려도 안전해야 한다.

        operational 을 먼저 지운다. canonical 을 먼저 지우면 실패했을 때 남은
        operational 기록이 가리킬 곳을 잃는다. 반대 순서라면 workspace 는 아직
        ``DELETING`` 으로 있어 다시 시도할 수 있다.

        감사 기록도 workspace 범위라 함께 사라진다. 전체 말소를 택한 결과이고,
        export 기능이 생기기 전까지는 그것이 정책이다.
        """
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

        reports = []
        for eraser in self._workspace_erasers:
            reports.append(await eraser.erase(risk_workspace_id))
        if reports:
            # 되돌릴 수 없는 일이므로 얼마나 지웠는지는 남긴다. 컬렉션 이름별
            # 개수를 임의 필드로 밀어 넣지는 않는다 — 구조화 로그는 안전을 위해
            # 필드를 고정해 두었고, 그 경계를 깨면서까지 남길 값은 아니다.
            self._observer.event(
                "workspace_data_erased",
                correlation=CorrelationIds(risk_workspace_id=risk_workspace_id),
                erased_document_count=sum(merge_counts(reports).values()),
            )
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
            occurred_at = self._clock()
            plan = plan_mount_disable(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                mount=mount,
                occurred_at=occurred_at,
                audit_event_id=self._id_factory("audit"),
            )
            await uow.mounts.save(plan.mount)
            await uow.audit.append(plan.audit_event)
            # 일시중지하면 이 mount 의 파일은 더 이상 감시되지 않는다. 그 상태에서
            # Risk 를 활성 목록에 남겨 두면 아직 추적 중인 것처럼 읽힌다. 사용자의
            # 판단이 아니라 외적 요인으로 관리가 끝난 것이므로 EXCLUDED 로 닫는다.
            # 다시 mount 되면 `should_revive` 가 되살린다.
            await exclude_mount_risks(
                uow,
                risk_workspace_id=risk_workspace_id,
                mount_id=mount_id,
                occurred_at=occurred_at,
                reason_safe="mount was disabled",
                id_factory=self._id_factory,
            )
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
            occurred_at = self._clock()
            plan = plan_mount_removal(
                actor_user_id=actor_user_id,
                actor_membership=actor,
                mount=mount,
                occurred_at=occurred_at,
                audit_event_id=self._id_factory("audit"),
            )
            # 해제는 일시중지보다 **더** 최종적인데 정리는 덜 했다. 마운트 기록만
            # 지우고 Risk 는 활성 목록에 남겨, 이미 없는 마운트의 파일이 아직 추적
            # 중인 것처럼 읽혔다.
            #
            # 일시중지와 같은 처분을 쓴다 — 사용자의 판단이 아니라 외적 요인으로
            # 관리가 끝난 것이다. 지우지 않으므로 "왜 그때 그렇게 판단했는가" 는
            # 해제 뒤에도 답할 수 있다.
            await exclude_mount_risks(
                uow,
                risk_workspace_id=risk_workspace_id,
                mount_id=mount_id,
                occurred_at=occurred_at,
                reason_safe="mount was removed",
                id_factory=self._id_factory,
            )
            await uow.mounts.remove(plan.mount_id)
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
