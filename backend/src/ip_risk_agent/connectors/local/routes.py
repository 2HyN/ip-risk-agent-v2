from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from iprisk_contracts.common import ChangeType, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange

from ..common.change_sink import SourceChangeSink
from ..common.fingerprint import local_change_fingerprint
from .identity import encode_local_artifact_id
from .staging_store import LocalStagingStore


class AuthzDependency(Protocol):
    """Agent 2 Spec §3/§37: VWS membership/role 판단은 Agent 1이 제공하는
    authz_dependency를 주입받아 쓴다 — Agent 2가 직접 Membership DB를
    읽지 않는다. 이 Protocol은 우리가 필요로 하는 최소 형태만 정의한다:
    mount_id에 대해 이 요청이 허용되면 조용히 반환, 아니면 스스로
    HTTPException(401/403)을 던진다."""

    async def __call__(self, request: Request, mount_id: str) -> None: ...


async def allow_all_authz(request: Request, mount_id: str) -> None:
    """개발/테스트 전용 기본값 — 아무 것도 검사하지 않는다.
    프로덕션 배포 전 반드시 Agent 1의 실제 authz_dependency로 교체해야 한다."""
    return None


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
    authz_dependency: AuthzDependency = allow_all_authz,
) -> APIRouter:
    router = APIRouter()

    @router.post("/desktop/staging", response_model=StagingUploadResponse)
    async def handle_staging_upload(request: Request, body: StagingUploadRequest) -> StagingUploadResponse:
        await authz_dependency(request, body.mount_id)

        ref = await staging_store.put(body.content, {})
        return StagingUploadResponse(object_name=ref.object_name)

    @router.post("/desktop/events", response_model=DesktopEventResponse)
    async def handle_desktop_event(request: Request, event: DesktopEventRequest) -> DesktopEventResponse:
        await authz_dependency(request, event.mount_id)

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
                display_name=event.previous_relative_path.rsplit("/", 1)[-1],
                path_hint=event.previous_relative_path,
            )

        display_name = event.relative_path.rsplit("/", 1)[-1]
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
            revision=event.revision,
            observed_at=datetime.now(timezone.utc),
            safe_metadata=safe_metadata,
        )

        await change_sink.persist(change)

        return DesktopEventResponse(status="ok", event_id=change.event_id)

    return router
