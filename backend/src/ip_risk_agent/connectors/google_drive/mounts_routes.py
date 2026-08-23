from __future__ import annotations

import json
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from iprisk_contracts.common import SafeMetadata

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.credential_vault import SourceCredentialVault
from ..common.errors import NotFoundError, SourceConnectorError
from .connection_lookup import (
    DriveConnectionCredentialLookup,
    DriveConnectionLookup,
)
from .tracking_scope import DriveTrackingScope


class DriveProviderFactory(Protocol):
    def create(self, token: dict) -> object: ...


class PickerSessionResponse(BaseModel):
    access_token: str


class DriveMountCreationRequest(BaseModel):
    """공유받은 **폴더 하나**를 붙인다 (§6.1 · 1-F).

    예전에는 고른 file id 의 목록을 받았다. 그러면 마운트한 뒤에 폴더에 넣은 파일이
    영영 잡히지 않는다 — 이 서비스를 쓰는 방법이 바로 그 "넣는 것" 이다.
    """

    risk_workspace_id: str
    folder_id: str = Field(min_length=1, max_length=256)
    display_metadata_by_file: dict[str, SafeMetadata] = {}


class DriveMountCreationResponse(BaseModel):
    server_mount_id: str
    source_workspace_id: str
    selected_file_ids: list[str] = Field(default_factory=list)


class DriveMountCreationCallback(Protocol):
    """Control의 canonical SourceWorkspace/Mount 생성. 우리는 선택된
    file_id 목록을 넘기고 server_mount_id/source_workspace_id를 돌려받는다."""

    async def create_drive_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        selected_file_ids: list[str],
    ) -> DriveMountCreationResponse: ...


class DriveInitialChangeSync(Protocol):
    async def initialize(
        self, *, mount_id: str, selected_file_ids: list[str]
    ) -> None: ...


class DriveUntrackRequest(BaseModel):
    risk_workspace_id: str
    artifact_id: str


class DriveUntrackResponse(BaseModel):
    artifact_id: str
    excluded_risk_ids: list[str] = Field(default_factory=list)
    remaining_file_count: int


class DriveUntrackCallback(Protocol):
    """Control 쪽 canonical 처리. artifact 를 보관하고 Risk 를 제외한다.

    Drive 의 추적 범위(file id 목록)는 canonical 상태가 아니라 이 connector 의 것이다.
    그래서 canonical 처리는 callback 에 맡기고, 감시를 실제로 끊는 일만 여기서 한다.
    """

    async def untrack_artifact(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        artifact_id: str,
    ) -> "DriveUntrackOutcome": ...


class DriveUntrackOutcome(Protocol):
    mount_id: str
    source_artifact_id: str
    excluded_risk_ids: tuple[str, ...]


def create_drive_mounts_router(
    *,
    provider_factory: DriveProviderFactory,
    credential_vault: SourceCredentialVault,
    connection_credential_lookup: DriveConnectionCredentialLookup,
    mount_connection_lookup: DriveConnectionLookup | None = None,
    tracking_scope_store,
    mount_creation_callback: DriveMountCreationCallback,
    untrack_callback: DriveUntrackCallback | None = None,
    initial_change_sync: DriveInitialChangeSync | None = None,
    connection_authz_dependency: AuthzDependency = deny_all_authz,
    mount_authz_dependency: AuthzDependency = deny_all_authz,
    workspace_authz_dependency: AuthzDependency = deny_all_authz,
) -> APIRouter:
    router = APIRouter()

    async def initialize_selection(
        *, mount_id: str, selected_file_ids: list[str] | None = None
    ) -> None:
        """마운트 직후 폴더를 한 번 훑는다.

        변경 피드는 커서를 잡은 **뒤**부터 준다. 이미 폴더에 있던 파일은 그것으로
        발견되지 않으므로 여기서 훑는다.
        """
        if initial_change_sync is None:
            return
        try:
            await initial_change_sync.initialize(
                mount_id=mount_id,
                selected_file_ids=selected_file_ids,
            )
        except SourceConnectorError as exc:
            raise HTTPException(
                status_code=503 if exc.retryable else 502,
                detail={
                    "code": "DRIVE_INITIAL_SYNC_FAILED",
                    "operation": "drive_file_metadata",
                    "provider_error": exc.category.value,
                    "retryable": exc.retryable,
                },
            ) from exc

    async def issue_picker_session(credential_ref) -> PickerSessionResponse:
        raw_token = await credential_vault.get(credential_ref)
        token = json.loads(raw_token)
        provider = provider_factory.create(token)

        try:
            access_token, _ = provider.get_access_token()
        except SourceConnectorError as exc:
            raise HTTPException(
                status_code=401, detail="drive connection requires reauthorization"
            ) from exc

        await credential_vault.update(credential_ref, json.dumps(provider.export_token()))

        return PickerSessionResponse(access_token=access_token)

    @router.post(
        "/api/v1/source-connections/{connection_id}/drive/picker-session",
        response_model=PickerSessionResponse,
    )
    async def create_picker_session(
        connection_id: str, request: Request
    ) -> PickerSessionResponse:
        await connection_authz_dependency(request, connection_id)
        try:
            credential_ref = await connection_credential_lookup.resolve_credential_ref(
                connection_id
            )
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown source connection") from exc
        return await issue_picker_session(credential_ref)

    @router.post(
        "/api/v1/source-mounts/{mount_id}/drive/picker-session",
        response_model=PickerSessionResponse,
    )
    async def create_active_picker_session(
        mount_id: str, request: Request
    ) -> PickerSessionResponse:
        await mount_authz_dependency(request, mount_id)
        if mount_connection_lookup is None:
            raise HTTPException(status_code=404, detail="unknown Drive mount")
        try:
            context = await mount_connection_lookup.resolve(mount_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown Drive mount") from exc
        return await issue_picker_session(context.credential_ref)

    @router.post(
        "/api/v1/source-connections/{connection_id}/drive/mounts",
        response_model=DriveMountCreationResponse,
    )
    async def create_mount(
        connection_id: str, request: Request, body: DriveMountCreationRequest
    ) -> DriveMountCreationResponse:
        await connection_authz_dependency(request, connection_id)
        await workspace_authz_dependency(request, body.risk_workspace_id)

        result = await mount_creation_callback.create_drive_mount(
            request,
            connection_id=connection_id,
            risk_workspace_id=body.risk_workspace_id,
            selected_file_ids=[body.folder_id],
        )

        await _set_tracked_folder(
            tracking_scope_store,
            mount_id=result.server_mount_id,
            folder_id=body.folder_id,
            display_metadata_by_file=body.display_metadata_by_file,
        )

        await initialize_selection(
            mount_id=result.server_mount_id, selected_file_ids=None
        )

        return result

    @router.post(
        "/api/v1/source-mounts/{mount_id}/drive/mounts",
        response_model=DriveMountCreationResponse,
    )
    async def create_additional_mount(
        mount_id: str, request: Request, body: DriveMountCreationRequest
    ) -> DriveMountCreationResponse:
        await mount_authz_dependency(request, mount_id)
        await workspace_authz_dependency(request, body.risk_workspace_id)
        if mount_connection_lookup is None:
            raise HTTPException(status_code=404, detail="unknown Drive mount")
        try:
            context = await mount_connection_lookup.resolve(mount_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown Drive mount") from exc
        if context.operational_connection_id is None:
            raise HTTPException(status_code=404, detail="unknown Drive mount")
        result = await mount_creation_callback.create_drive_mount(
            request,
            connection_id=context.operational_connection_id,
            risk_workspace_id=body.risk_workspace_id,
            selected_file_ids=[body.folder_id],
        )
        await _set_tracked_folder(
            tracking_scope_store,
            mount_id=result.server_mount_id,
            folder_id=body.folder_id,
            display_metadata_by_file=body.display_metadata_by_file,
        )
        await initialize_selection(
            mount_id=result.server_mount_id, selected_file_ids=None
        )
        return result

    # `drive/untrack` 은 없앴다 (§6.1 · 1-F).
    #
    # 폴더를 보는 지금 "이 파일만 추적 해제" 는 성립하지 않는다. 범위에서 뺄 방법이
    # 없고, Risk 만 닫아 두면 **그 파일의 다음 변경에 되살아난다.** 추적을 끊는
    # 방법은 하나뿐이다 — 폴더 밖으로 옮긴다. 실측에서 그것이 `removed` 로 오고
    # (§2.1.1), 1-D 가 그때 Risk 를 닫는다.

    return router


async def _set_tracked_folder(
    tracking_scope_store,
    *,
    mount_id: str,
    folder_id: str,
    display_metadata_by_file: dict[str, SafeMetadata],
) -> None:
    """이 마운트가 볼 폴더를 정한다.

    예전 함수는 고른 file id 를 **더했다** — 덮어쓰면 이전에 추적하던 파일이 조용히
    감시에서 빠졌기 때문이다. 폴더 하나를 보는 지금은 그 문제가 없다. 무엇이 추적
    대상인지는 명단이 아니라 **폴더 안에 있는가**로 정해진다.
    """
    await tracking_scope_store.save(
        mount_id,
        DriveTrackingScope(
            mount_id=mount_id,
            folder_id=folder_id,
            display_metadata_by_file=dict(display_metadata_by_file),
        ),
    )
