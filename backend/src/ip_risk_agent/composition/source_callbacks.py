"""Source 라우터의 생성 콜백을 Control canonical 등록으로 잇는다.

Agent 2 는 provider 식별자와 선택 결과만 넘기고, canonical
SourceConnection / SourceWorkspace / Mount 생성은 Control 이 한다
(AGENT_2_DELIVERY 9-1). 그 사이 변환이 여기 있다.

키 설계 원칙 — ``registration_key`` / ``connection_key`` / ``source_workspace_key``
는 재시도 동안 **같은 값**이어야 한다. Control 이 이 값을 deterministic canonical
ID 로 바꾸므로, 매번 새 값을 만들면 재시도마다 다른 Mount 가 생긴다
(AGENT_1_DELIVERY 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status
from iprisk_contracts.common import SourceType

from ip_risk_agent.application.public_facade import (
    SourceMetadataRegistrationCallback,
    SourceMetadataRegistrationCommand,
)
from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.github.mounts_routes import GitHubMountCreationResponse
from ip_risk_agent.connectors.google_drive.mounts_routes import (
    DriveMountCreationResponse,
)
from ip_risk_agent.connectors.local.routes import (
    MountRegistrationRequest,
    MountRegistrationResponse,
)

from .authz import current_user_id


@dataclass
class ConnectionRegistry:
    """connection_id -> (risk_workspace_id, owner_user_id) 레지스트리.

    Control 은 connection 을 workspace 로 되짚는 공개 메서드를 두지 않았고,
    Agent 2 는 Control 내부를 import 할 수 없다. 그 틈을 Integration 이 메운다.
    connection 스코프 라우트의 authz 가 이 값을 쓴다.
    """

    _workspace_by_connection: dict[str, str] = field(default_factory=dict)
    _owner_by_connection: dict[str, str] = field(default_factory=dict)

    def remember(
        self, connection_id: str, *, risk_workspace_id: str, owner_user_id: str
    ) -> None:
        self._workspace_by_connection[connection_id] = risk_workspace_id
        self._owner_by_connection[connection_id] = owner_user_id

    async def resolve_workspace(self, connection_id: str) -> str | None:
        return self._workspace_by_connection.get(connection_id)

    def owner_of(self, connection_id: str) -> str | None:
        return self._owner_by_connection.get(connection_id)


@dataclass
class DeviceRegistry:
    """device_id -> app_user 연결. 로컬 desktop 경로에서만 쓴다."""

    _user_by_device: dict[str, str] = field(default_factory=dict)
    _label_by_device: dict[str, str] = field(default_factory=dict)

    def remember(self, device_id: str, *, user_id: str, label: str) -> None:
        self._user_by_device[device_id] = user_id
        self._label_by_device[device_id] = label

    def user_of(self, device_id: str) -> str | None:
        return self._user_by_device.get(device_id)


def _conflict(reason: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)


class SourceRegistrationService:
    """다섯 개 생성 콜백의 공통 구현.

    Agent 2 라우터들은 각자 다른 Protocol 을 기대하지만, 하는 일은 모두
    "provider 선택 결과를 canonical 등록 명령으로 바꿔 Control 에 넘긴다"로 같다.
    """

    def __init__(
        self,
        register_metadata: SourceMetadataRegistrationCallback,
        *,
        connections: ConnectionRegistry,
        devices: DeviceRegistry,
    ) -> None:
        self._register = register_metadata
        self._connections = connections
        self._devices = devices

    # ---------------------------------------------------------------- Drive

    async def create_drive_connection(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        provider_subject: str,
        provider_email: str,
        credential_ref: CredentialRef,
    ) -> str:
        actor = current_user_id(request)
        # 연결 단계에서는 아직 추적 대상이 없다. Drive 계정 하나를 가리키는
        # 안정 키로 connection 을 만들고, Mount 는 파일 선택 이후에 만든다.
        connection_key = f"google-drive:{provider_subject}"
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{risk_workspace_id}:{connection_key}",
                actor_user_id=actor,
                risk_workspace_id=risk_workspace_id,
                source_type=SourceType.GOOGLE_DRIVE,
                connection_key=connection_key,
                source_workspace_key=f"{connection_key}:pending",
                external_scope_id="pending",
                source_workspace_display_name=provider_email or "Google Drive",
                mount_alias=provider_email or "Google Drive",
                provider_subject=provider_subject,
                provider_account_label=provider_email,
                credential_ref=credential_ref.key_id,
            )
        )
        self._connections.remember(
            registration.connection_id,
            risk_workspace_id=risk_workspace_id,
            owner_user_id=actor,
        )
        return registration.connection_id

    async def create_drive_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        selected_file_ids: list[str],
    ) -> DriveMountCreationResponse:
        actor = current_user_id(request)
        if not selected_file_ids:
            raise _conflict("at least one Drive file must be selected")
        # 선택 집합이 같으면 재시도해도 같은 Mount 가 되도록 정렬해 키를 만든다.
        scope_id = ",".join(sorted(selected_file_ids))
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{risk_workspace_id}:{connection_id}:{scope_id}",
                actor_user_id=actor,
                risk_workspace_id=risk_workspace_id,
                source_type=SourceType.GOOGLE_DRIVE,
                connection_key=connection_id,
                source_workspace_key=f"{connection_id}:{scope_id}",
                external_scope_id=scope_id,
                source_workspace_display_name=(
                    f"Drive ({len(selected_file_ids)} items)"
                ),
                mount_alias=f"Drive ({len(selected_file_ids)} items)",
                tracking_config_safe={
                    "selected_file_count": len(selected_file_ids)
                },
            )
        )
        return DriveMountCreationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )

    # --------------------------------------------------------------- GitHub

    async def create_github_connection(
        self, request: Request, *, risk_workspace_id: str, installation_id: str
    ) -> str:
        actor = current_user_id(request)
        connection_key = f"github:{installation_id}"
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{risk_workspace_id}:{connection_key}",
                actor_user_id=actor,
                risk_workspace_id=risk_workspace_id,
                source_type=SourceType.GITHUB,
                connection_key=connection_key,
                source_workspace_key=f"{connection_key}:pending",
                external_scope_id="pending",
                source_workspace_display_name=(
                    f"GitHub installation {installation_id}"
                ),
                mount_alias=f"GitHub installation {installation_id}",
                provider_subject=installation_id,
                provider_account_label=f"installation {installation_id}",
            )
        )
        self._connections.remember(
            registration.connection_id,
            risk_workspace_id=risk_workspace_id,
            owner_user_id=actor,
        )
        return registration.connection_id

    async def create_github_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        owner: str,
        repo: str,
        tracked_branch: str,
    ) -> GitHubMountCreationResponse:
        actor = current_user_id(request)
        scope_id = f"{owner}/{repo}@{tracked_branch}"
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{risk_workspace_id}:{connection_id}:{scope_id}",
                actor_user_id=actor,
                risk_workspace_id=risk_workspace_id,
                source_type=SourceType.GITHUB,
                connection_key=connection_id,
                source_workspace_key=f"{connection_id}:{scope_id}",
                external_scope_id=scope_id,
                source_workspace_display_name=f"{owner}/{repo}",
                mount_alias=f"{owner}/{repo} ({tracked_branch})",
                tracking_config_safe={"tracked_branch": tracked_branch},
            )
        )
        return GitHubMountCreationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )

    # ---------------------------------------------------------------- Local

    async def register_device(
        self, request: Request, device_id: str, device_label: str
    ) -> None:
        actor = current_user_id(request)
        self._devices.remember(device_id, user_id=actor, label=device_label)

    async def create_local_mount(
        self, request: Request, body: MountRegistrationRequest
    ) -> MountRegistrationResponse:
        actor = current_user_id(request)
        owner = self._devices.user_of(body.device_id)
        if owner is not None and owner != actor:
            # 남의 기기를 자기 VWS 에 붙이지 못하게 한다.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="device belongs to a different user",
            )
        # canonical_root_path 는 요청 스키마에 없다(Agent 2 Spec 25).
        # 절대경로가 cloud metadata 로 나가지 않도록 device_id 만 스코프로 쓴다.
        scope_id = body.device_id
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{body.risk_workspace_id}:local:{scope_id}",
                actor_user_id=actor,
                risk_workspace_id=body.risk_workspace_id,
                source_type=SourceType.LOCAL,
                connection_key=f"local:{scope_id}",
                source_workspace_key=f"local:{scope_id}",
                external_scope_id=scope_id,
                source_workspace_display_name=f"Local device {body.device_id}",
                mount_alias=f"Local device {body.device_id}",
                provider_subject=body.device_id,
                tracking_config_safe={
                    "include_pattern_count": len(body.include_patterns),
                    "exclude_pattern_count": len(body.exclude_patterns),
                },
            )
        )
        self._connections.remember(
            registration.connection_id,
            risk_workspace_id=body.risk_workspace_id,
            owner_user_id=actor,
        )
        return MountRegistrationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )


__all__ = ["ConnectionRegistry", "DeviceRegistry", "SourceRegistrationService"]
