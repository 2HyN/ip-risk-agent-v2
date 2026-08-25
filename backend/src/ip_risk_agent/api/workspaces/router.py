"""Risk Workspace, membership, and mount metadata routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import AwareDatetime, Field, model_validator

from ip_risk_agent.application.auth import AuthenticationService
from ip_risk_agent.application.artifact_view import (
    current_change_for_artifact,
    latest_job,
    needs_attention,
)
from ip_risk_agent.application.repositories import (
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.core.artifacts import ArtifactAvailability
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    MembershipRole,
    MembershipStatus,
    VwsAction,
)
from ip_risk_agent.core.mounts import MountStatus
from ip_risk_agent.core.risk import ReviewDisposition, RiskLifecycleState
from ip_risk_agent.core.workspaces import RiskWorkspaceStatus

from ..authorization import require_workspace_action
from ..common import (
    CsrfGuard,
    CursorCodec,
    CurrentPrincipal,
    CurrentPrincipalDependency,
    Page,
    StrictApiModel,
    opaque_etag,
    paginate,
)


class WorkspaceResponse(StrictApiModel):
    id: str
    name: str
    description: str | None
    owner_user_id: str
    security_policy_version: str
    retention_policy_version: str
    created_at: datetime
    updated_at: datetime
    status: RiskWorkspaceStatus


class WorkspaceListItemResponse(WorkspaceResponse):
    """목록 전용 — 각 workspace 에서 내가 맡은 역할을 함께 준다.

    화면이 workspace 마다 membership 을 따로 묻지 않게 하기 위한 필드라 목록
    라우트만 채운다. 단건 조회의 역할은 /membership 이 정답이다.
    """

    my_role: MembershipRole | None = None


class WorkspaceCreateRequest(StrictApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)


class WorkspaceUpdateRequest(StrictApiModel):
    expected_updated_at: AwareDatetime
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def require_change(self):
        if not ({"name", "description"} & self.model_fields_set):
            raise ValueError("workspace update requires name or description")
        return self


class MembershipResponse(StrictApiModel):
    id: str
    risk_workspace_id: str
    user_id: str
    role: MembershipRole
    status: MembershipStatus
    invited_by: str
    created_at: datetime
    updated_at: datetime
    # id 만으로는 사람이 사람을 못 알아본다. 목록 라우트가 채워서 보낸다 —
    # 다른 라우트(내 멤버십 등)는 안 채워도 되도록 선택 필드다.
    user_email: str | None = None
    user_display_name: str | None = None
    invited_by_email: str | None = None


class InvitationResponse(StrictApiModel):
    id: str
    risk_workspace_id: str
    email: str
    role: MembershipRole
    status: str
    invited_by: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None


class InvitationCreateRequest(StrictApiModel):
    email: str = Field(min_length=3, max_length=320)
    role: MembershipRole
    expires_at: AwareDatetime | None = None


class MembershipUpdateRequest(StrictApiModel):
    role: MembershipRole


class MountResponse(StrictApiModel):
    id: str
    risk_workspace_id: str
    source_workspace_id: str
    alias: str
    mounted_by_user_id: str
    source_connection_id: str
    status: MountStatus
    created_at: datetime
    updated_at: datetime


class MountAliasUpdateRequest(StrictApiModel):
    alias: str = Field(min_length=1, max_length=200)


class PendingInvitationResponse(InvitationResponse):
    workspace_name: str
    acceptance_available: bool
    #: 초대한 사람의 이메일. id 는 화면에서 사람이 못 알아본다.
    invited_by_email: str | None = None


class InvitationAcceptanceResponse(StrictApiModel):
    invitation: InvitationResponse
    membership: MembershipResponse
    workspace: WorkspaceResponse


class SourceHealthSummaryResponse(StrictApiModel):
    active: int
    action_required: int
    offline: int
    disabled: int


class WorkspaceDashboardResponse(StrictApiModel):
    new_risks: int
    monitoring_risks: int
    resolved_recently: int
    analysis_failed: int
    source_health: SourceHealthSummaryResponse


class AnalysisProgressItemResponse(StrictApiModel):
    artifact_id: str
    display_name: str
    status: str
    failure_safe: str | None = None


class AnalysisProgressResponse(StrictApiModel):
    """지금 이 워크스페이스에서 분석이 어디까지 왔는가.

    화면의 진행 바가 주기적으로 묻는 값이라 **문서 단위**로 센다 — 대시보드의
    실패 계산과 같은 이유로, 판본이 밀려 끝난 실행은 세지 않는다. ``items`` 에는
    끝나지 않았거나 실패한 문서만 담는다. 다 끝났으면 비어 있다.
    """

    total: int
    waiting: int
    queued: int
    running: int
    succeeded: int
    failed: int
    inconclusive: int
    items: list[AnalysisProgressItemResponse]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceRouterDependencies:
    unit_of_work_factory: ControlUnitOfWorkFactory
    administration: WorkspaceAdministrationService
    authentication: AuthenticationService
    cursor_codec: CursorCodec
    initial_security_policy_version: str = "security-v1"
    initial_retention_policy_version: str = "balanced-v1"


def create_workspaces_router(deps: WorkspaceRouterDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])
    current = CurrentPrincipalDependency(deps.authentication)
    csrf = CsrfGuard()

    @router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
    async def create_workspace(
        body: WorkspaceCreateRequest,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        plan = await deps.administration.create_workspace(
            owner_user_id=principal.user.id,
            name=body.name,
            description=body.description,
            security_policy_version=deps.initial_security_policy_version,
            retention_policy_version=deps.initial_retention_policy_version,
        )
        return plan.workspace

    @router.get("", response_model=Page[WorkspaceListItemResponse])
    async def list_workspaces(
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        async with deps.unit_of_work_factory() as uow:
            values = await uow.workspaces.list_for_user(principal.user.id)
            selected, next_cursor = paginate(
                values,
                cursor=cursor,
                limit=limit,
                scope=f"workspaces:{principal.user.id}",
                codec=deps.cursor_codec,
            )
            items = []
            for workspace in selected:
                membership = await uow.memberships.get(
                    workspace.id, principal.user.id
                )
                items.append(
                    WorkspaceListItemResponse(
                        **WorkspaceResponse.model_validate(
                            workspace, from_attributes=True
                        ).model_dump(),
                        my_role=None if membership is None else membership.role,
                    )
                )
        return Page(items=items, next_cursor=next_cursor)

    @router.get("/{vws_id}", response_model=WorkspaceResponse)
    async def get_workspace(
        vws_id: str,
        response: Response,
        principal: CurrentPrincipal = Depends(current),
    ):
        workspace, _ = await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        response.headers["ETag"] = opaque_etag(
            "workspace",
            workspace.updated_at.isoformat(),
        )
        return workspace

    @router.get("/{vws_id}/membership", response_model=MembershipResponse)
    async def get_current_membership(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
    ):
        _workspace, membership = await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        return membership

    @router.get("/{vws_id}/dashboard", response_model=WorkspaceDashboardResponse)
    async def get_dashboard(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
    ):
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        async with deps.unit_of_work_factory() as uow:
            risks = await uow.risks.list_for_workspace(vws_id)
            mounts = await uow.mounts.list_for_workspace(vws_id)
            change_events = await uow.change_events.list_for_workspace(vws_id)
            # 실패는 기록을 세는 것이 아니라 **문서를 세는 것**이다. 한 번의 편집이
            # 판본을 여럿 만들면 밀려서 끝난 실행이 여럿 남는데, 그것까지 세면
            # 고칠 때마다 "분석 실패" 가 늘고 뒤이어 성공해도 줄지 않는다. Sources
            # 화면은 이미 지금 판본의 실행만 보므로 두 화면이 서로 어긋났다.
            changes_by_artifact: dict[str, list] = {}
            for event in change_events:
                if event.artifact_id is not None:
                    changes_by_artifact.setdefault(event.artifact_id, []).append(event)
            # 비활성화한 소스의 실패는 세지 않는다 — 사용자가 소스를 껐다는 것은
            # "지금은 관리 대상이 아니다" 는 뜻이라, 남겨 두면 지울 수 없는 경고가 된다.
            disabled_mounts = {
                mount.id for mount in mounts if mount.status is MountStatus.DISABLED
            }
            failed_artifacts = 0
            for artifact in await uow.artifacts.list_for_workspace(vws_id):
                if artifact.mount_id in disabled_mounts:
                    continue
                change = current_change_for_artifact(
                    changes_by_artifact.get(artifact.id),
                    await uow.artifacts.get_state(artifact.id),
                )
                if change is None:
                    continue
                job = latest_job(await uow.analysis_jobs.list_for_change(change.id))
                if needs_attention(job):
                    failed_artifacts += 1
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        return WorkspaceDashboardResponse(
            new_risks=sum(
                risk.lifecycle_state is RiskLifecycleState.NEW for risk in risks
            ),
            monitoring_risks=sum(
                risk.lifecycle_state is not RiskLifecycleState.RESOLVED
                and risk.review_disposition is ReviewDisposition.MONITORING
                for risk in risks
            ),
            resolved_recently=sum(
                risk.lifecycle_state is RiskLifecycleState.RESOLVED
                and risk.resolved_at is not None
                and risk.resolved_at >= recent_cutoff
                for risk in risks
            ),
            analysis_failed=failed_artifacts,
            source_health=SourceHealthSummaryResponse(
                active=sum(mount.status is MountStatus.ACTIVE for mount in mounts),
                action_required=sum(
                    mount.status
                    in {MountStatus.REAUTH_REQUIRED, MountStatus.MANAGER_ACTION_REQUIRED}
                    for mount in mounts
                ),
                offline=sum(mount.status is MountStatus.SOURCE_OFFLINE for mount in mounts),
                disabled=sum(mount.status is MountStatus.DISABLED for mount in mounts),
            ),
        )

    @router.get("/{vws_id}/analyses/progress", response_model=AnalysisProgressResponse)
    async def get_analysis_progress(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
    ):
        """화면이 폴링하는 작업 현황. 대시보드와 같은 눈으로 센다.

        문서마다 **지금 판본을 맡은 변경**의 마지막 실행 하나만 본다. 실행 기록
        전부를 세면 문서를 고칠 때마다 진행률이 뒤로 간다.
        """
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        counts = {
            "WAITING": 0,
            "QUEUED": 0,
            "RUNNING": 0,
            "SUCCEEDED": 0,
            "FAILED": 0,
            "INCONCLUSIVE": 0,
        }
        items: list[AnalysisProgressItemResponse] = []
        async with deps.unit_of_work_factory() as uow:
            changes_by_artifact: dict[str, list] = {}
            for event in await uow.change_events.list_for_workspace(vws_id):
                if event.artifact_id is not None:
                    changes_by_artifact.setdefault(event.artifact_id, []).append(event)
            for artifact in await uow.artifacts.list_for_workspace(vws_id):
                state = await uow.artifacts.get_state(artifact.id)
                if (
                    state is not None
                    and state.availability_state is ArtifactAvailability.DELETED
                ):
                    continue
                change = current_change_for_artifact(
                    changes_by_artifact.get(artifact.id), state
                )
                failure: str | None = None
                if change is None:
                    status_key = "WAITING"
                else:
                    job = latest_job(await uow.analysis_jobs.list_for_change(change.id))
                    if job is None:
                        status_key = "WAITING"
                    elif job.status.value == "FAILED":
                        # 밀려서 끝난 실행은 실패가 아니다 — 새 판본이 자리를
                        # 맡았고 사람이 할 일이 없다.
                        status_key = "FAILED" if needs_attention(job) else "WAITING"
                        failure = job.failure_safe if needs_attention(job) else None
                    else:
                        status_key = job.status.value
                counts[status_key] += 1
                if status_key not in {"SUCCEEDED", "INCONCLUSIVE"} and len(items) < 50:
                    items.append(
                        AnalysisProgressItemResponse(
                            artifact_id=artifact.id,
                            display_name=artifact.display_name,
                            status=status_key,
                            failure_safe=failure,
                        )
                    )
        return AnalysisProgressResponse(
            total=sum(counts.values()),
            waiting=counts["WAITING"],
            queued=counts["QUEUED"],
            running=counts["RUNNING"],
            succeeded=counts["SUCCEEDED"],
            failed=counts["FAILED"],
            inconclusive=counts["INCONCLUSIVE"],
            items=items,
            generated_at=datetime.now(timezone.utc),
        )

    @router.patch("/{vws_id}", response_model=WorkspaceResponse)
    async def update_workspace(
        vws_id: str,
        body: WorkspaceUpdateRequest,
        response: Response,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        workspace = await deps.administration.update_workspace(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            expected_updated_at=body.expected_updated_at,
            name=body.name,
            description=body.description,
            description_provided="description" in body.model_fields_set,
        )
        response.headers["ETag"] = opaque_etag(
            "workspace",
            workspace.updated_at.isoformat(),
        )
        return workspace

    @router.delete("/{vws_id}", response_model=WorkspaceResponse)
    async def delete_workspace(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        plan = await deps.administration.request_workspace_deletion(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
        )
        return plan.workspace

    @router.get("/{vws_id}/members", response_model=Page[MembershipResponse])
    async def list_members(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        async with deps.unit_of_work_factory() as uow:
            values = await uow.memberships.list_members(vws_id)
        values = tuple(
            member for member in values if member.status is MembershipStatus.ACTIVE
        )
        selected, next_cursor = paginate(
            values,
            cursor=cursor,
            limit=limit,
            scope=f"members:{vws_id}",
            codec=deps.cursor_codec,
        )
        # id 만으로는 사람이 사람을 못 알아본다 — 이 페이지에 나올 사용자만
        # 이름과 이메일을 되짚어 함께 싣는다.
        user_ids = {member.user_id for member in selected} | {
            member.invited_by for member in selected
        }
        async with deps.unit_of_work_factory() as uow:
            users = {user_id: await uow.users.get(user_id) for user_id in user_ids}
        items = []
        for member in selected:
            user = users.get(member.user_id)
            inviter = users.get(member.invited_by)
            items.append(
                MembershipResponse(
                    **MembershipResponse.model_validate(member).model_dump(
                        exclude={"user_email", "user_display_name", "invited_by_email"}
                    ),
                    user_email=None if user is None else user.email,
                    user_display_name=None if user is None else user.display_name,
                    invited_by_email=None if inviter is None else inviter.email,
                )
            )
        return Page(items=items, next_cursor=next_cursor)

    @router.post(
        "/{vws_id}/members/invitations",
        response_model=InvitationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def invite_member(
        vws_id: str,
        body: InvitationCreateRequest,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        plan = await deps.administration.invite_member(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            email=body.email,
            role=body.role,
            expires_at=body.expires_at,
        )
        return plan.invitation

    @router.patch("/{vws_id}/members/{user_id}", response_model=MembershipResponse)
    async def update_member(
        vws_id: str,
        user_id: str,
        body: MembershipUpdateRequest,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        plan = await deps.administration.change_member_role(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            target_user_id=user_id,
            new_role=body.role,
        )
        return plan.membership

    @router.delete("/{vws_id}/members/{user_id}", response_model=MembershipResponse)
    async def remove_member(
        vws_id: str,
        user_id: str,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        plan = await deps.administration.remove_member(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            target_user_id=user_id,
        )
        return plan.membership

    @router.get("/{vws_id}/mounts", response_model=Page[MountResponse])
    async def list_mounts(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        async with deps.unit_of_work_factory() as uow:
            values = await uow.mounts.list_for_workspace(vws_id)
        selected, next_cursor = paginate(
            values,
            cursor=cursor,
            limit=limit,
            scope=f"mounts:{vws_id}",
            codec=deps.cursor_codec,
        )
        return Page(items=list(selected), next_cursor=next_cursor)

    @router.get("/{vws_id}/mounts/{mount_id}", response_model=MountResponse)
    async def get_mount(
        vws_id: str,
        mount_id: str,
        principal: CurrentPrincipal = Depends(current),
    ):
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.VWS_VIEW,
        )
        async with deps.unit_of_work_factory() as uow:
            mount = await uow.mounts.get(mount_id)
        if mount is None or mount.risk_workspace_id != vws_id:
            raise RecordNotFoundError(f"mount was not found: {mount_id!r}")
        return mount

    @router.patch("/{vws_id}/mounts/{mount_id}/alias", response_model=MountResponse)
    async def rename_mount(
        vws_id: str,
        mount_id: str,
        body: MountAliasUpdateRequest,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        return (
            await deps.administration.rename_mount(
                risk_workspace_id=vws_id,
                actor_user_id=principal.user.id,
                mount_id=mount_id,
                new_alias=body.alias,
            )
        ).mount

    @router.post("/{vws_id}/mounts/{mount_id}/disable", response_model=MountResponse)
    async def disable_mount(
        vws_id: str,
        mount_id: str,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        return (
            await deps.administration.disable_mount(
                risk_workspace_id=vws_id,
                actor_user_id=principal.user.id,
                mount_id=mount_id,
            )
        ).mount

    @router.delete(
        "/{vws_id}/mounts/{mount_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_mount(
        vws_id: str,
        mount_id: str,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ) -> Response:
        await deps.administration.remove_mount(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            mount_id=mount_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def create_invitations_router(deps: WorkspaceRouterDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])
    current = CurrentPrincipalDependency(deps.authentication)
    csrf = CsrfGuard()

    @router.get("", response_model=Page[PendingInvitationResponse])
    async def list_pending_invitations(
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        async with deps.unit_of_work_factory() as uow:
            invitations = await uow.memberships.list_invitations_for_email(
                principal.user.email
            )
            invitations = tuple(
                invitation
                for invitation in invitations
                if invitation.status is InvitationStatus.PENDING
            )
            values = []
            for invitation in invitations:
                workspace = await uow.workspaces.get(invitation.risk_workspace_id)
                if workspace is not None:
                    acceptance_available = (
                        invitation.expires_at is None
                        or invitation.expires_at > datetime.now(timezone.utc)
                    )
                    inviter = await uow.users.get(invitation.invited_by)
                    values.append(
                        PendingInvitationResponse(
                            **InvitationResponse.model_validate(invitation).model_dump(),
                            workspace_name=workspace.name,
                            acceptance_available=acceptance_available,
                            invited_by_email=(
                                None if inviter is None else inviter.email
                            ),
                        )
                    )
        selected, next_cursor = paginate(
            tuple(values),
            cursor=cursor,
            limit=limit,
            scope=f"invitations:{principal.user.id}",
            codec=deps.cursor_codec,
        )
        return Page(items=list(selected), next_cursor=next_cursor)

    @router.post(
        "/{invitation_id}/accept",
        response_model=InvitationAcceptanceResponse,
    )
    async def accept_invitation(
        invitation_id: str,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        plan = await deps.administration.accept_invitation(
            invitation_id=invitation_id,
            authenticated_user_id=principal.user.id,
            verified_email=principal.user.email,
        )
        async with deps.unit_of_work_factory() as uow:
            workspace = await uow.workspaces.get(plan.membership.risk_workspace_id)
        if workspace is None:
            raise RecordNotFoundError("invitation workspace was not found")
        return InvitationAcceptanceResponse(
            invitation=InvitationResponse.model_validate(plan.invitation),
            membership=MembershipResponse.model_validate(plan.membership),
            workspace=WorkspaceResponse.model_validate(workspace),
        )

    return router


__all__ = [
    "WorkspaceResponse",
    "WorkspaceRouterDependencies",
    "create_invitations_router",
    "create_workspaces_router",
]
