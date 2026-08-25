from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from iprisk_contracts.common import ChangeType, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange
from ip_risk_agent.core.artifacts.naming import display_name_for

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.change_sink import SourceChangeSink
from ..common.fingerprint import local_change_fingerprint
from .identity import encode_local_artifact_id
from .staging_store import LocalStagingStore


class DeviceRegistrationRequest(BaseModel):
    device_id: str
    device_label: str


class DeviceRegistrationResponse(BaseModel):
    status: str


class DeviceRegistrationCallback(Protocol):
    """Agent 2 Spec §36: device_id를 app_user에 연결하는 건 Control의
    canonical 저장소 몫이다. request를 그대로 넘겨서, 실제 구현이
    세션/토큰에서 app_user를 추출해 연결할 수 있게 한다."""

    async def register_device(self, request: Request, device_id: str, device_label: str) -> None: ...


class MountRegistrationRequest(BaseModel):
    risk_workspace_id: str
    device_id: str
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    # canonical_root_path는 의도적으로 여기 없다 (Agent2 Spec §25: 절대
    # Cloud Contract로 canonical_root_path를 내보내지 않는다).
    #: 폴더의 **마지막 이름 하나**만 — 경로가 아니다 (§25 유지). 화면의 마운트
    #: 이름으로 쓰인다. 구버전 데스크톱은 보내지 않으므로 선택 필드다.
    folder_name: str | None = None


class MountRegistrationResponse(BaseModel):
    server_mount_id: str
    source_workspace_id: str


class MountCreationCallback(Protocol):
    """Agent 2 Spec §24: 실제 SourceWorkspace/Mount canonical 생성은
    Control 몫이다. 우리는 로컬에서 이미 결정한 정보(device_id, 패턴)를
    넘기고 server_mount_id/source_workspace_id를 돌려받기만 한다."""

    async def create_local_mount(self, request: Request, body: MountRegistrationRequest) -> MountRegistrationResponse: ...


class StagingUploadRequest(BaseModel):
    mount_id: str
    content: str


class StagingUploadResponse(BaseModel):
    object_name: str


class DesktopEventRequest(BaseModel):
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    device_id: str
    relative_path: str
    change_type: Literal["CREATE", "UPDATE", "DELETE", "MOVE"]
    revision: str | None = None
    staging_object_name: str | None = None
    previous_relative_path: str | None = None


class DesktopEventResponse(BaseModel):
    status: str
    event_id: str


def create_local_desktop_router(
    *,
    staging_store: LocalStagingStore,
    change_sink: SourceChangeSink,
    device_registration_callback: DeviceRegistrationCallback,
    mount_creation_callback: MountCreationCallback,
    device_registration_authz_dependency: AuthzDependency = deny_all_authz,
    workspace_authz_dependency: AuthzDependency = deny_all_authz,
    mount_authz_dependency: AuthzDependency = deny_all_authz,
) -> APIRouter:
    router = APIRouter()

    @router.post("/desktop/devices/register", response_model=DeviceRegistrationResponse)
    async def handle_device_register(
        request: Request, body: DeviceRegistrationRequest
    ) -> DeviceRegistrationResponse:
        await device_registration_authz_dependency(request, "")
        await device_registration_callback.register_device(request, body.device_id, body.device_label)
        return DeviceRegistrationResponse(status="ok")

    @router.post("/desktop/mounts/register", response_model=MountRegistrationResponse)
    async def handle_mount_register(
        request: Request, body: MountRegistrationRequest
    ) -> MountRegistrationResponse:
        await workspace_authz_dependency(request, body.risk_workspace_id)
        return await mount_creation_callback.create_local_mount(request, body)

    @router.post("/desktop/staging", response_model=StagingUploadResponse)
    async def handle_staging_upload(request: Request, body: StagingUploadRequest) -> StagingUploadResponse:
        await mount_authz_dependency(request, body.mount_id)

        ref = await staging_store.put(body.content, {})
        return StagingUploadResponse(object_name=ref.object_name)

    @router.post("/desktop/events", response_model=DesktopEventResponse)
    async def handle_desktop_event(request: Request, event: DesktopEventRequest) -> DesktopEventResponse:
        await mount_authz_dependency(request, event.mount_id)

        if event.change_type != "DELETE" and not event.staging_object_name:
            raise HTTPException(
                status_code=400, detail="staging_object_name is required for non-DELETE events"
            )
        if event.change_type == "MOVE" and not event.previous_relative_path:
            raise HTTPException(
                status_code=400, detail="previous_relative_path is required for MOVE events"
            )

        artifact_id = encode_local_artifact_id(
            device_id=event.device_id, mount_id=event.mount_id, relative_path=event.relative_path
        )
        content_marker = event.staging_object_name or "deleted"
        fingerprint = local_change_fingerprint(
            device_id=event.device_id,
            mount_id=event.mount_id,
            relative_path=event.relative_path,
            content_fingerprint=event.revision or content_marker,
        )

        safe_metadata: dict[str, str] = {}
        if event.staging_object_name:
            safe_metadata["staging_object_name"] = event.staging_object_name

        previous_artifact = None
        if event.change_type == "MOVE" and event.previous_relative_path:
            previous_artifact_id = encode_local_artifact_id(
                device_id=event.device_id,
                mount_id=event.mount_id,
                relative_path=event.previous_relative_path,
            )
            previous_artifact = SourceArtifactRef(
                source_artifact_id=previous_artifact_id,
                display_name=display_name_for(event.previous_relative_path),
                path_hint=event.previous_relative_path,
            )

        display_name = display_name_for(event.relative_path)
        change = SourceChange(
            contract_version="1",
            event_id=fingerprint,
            provider_event_id=None,
            event_fingerprint=fingerprint,
            risk_workspace_id=event.risk_workspace_id,
            mount_id=event.mount_id,
            source_workspace_id=event.source_workspace_id,
            source_type=SourceType.LOCAL,
            artifact=SourceArtifactRef(
                source_artifact_id=artifact_id, display_name=display_name, path_hint=event.relative_path
            ),
            previous_artifact=previous_artifact,
            change_type=ChangeType[event.change_type],
            # Local 에는 provider 가 주는 판본이 없다. 기기가 내용 해시를 보내고,
            # 지운 경우처럼 내용이 없을 때는 fingerprint 가 이미 쓰고 있는 표시를
            # 그대로 쓴다. 판본이 비면 계약이 변경 자체를 거절한다.
            revision=event.revision or content_marker,
            observed_at=datetime.now(timezone.utc),
            safe_metadata=safe_metadata,
        )

        await change_sink.persist(change)

        return DesktopEventResponse(status="ok", event_id=change.event_id)

    return router
