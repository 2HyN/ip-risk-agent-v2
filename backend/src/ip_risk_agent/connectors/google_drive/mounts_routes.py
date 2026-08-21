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
    risk_workspace_id: str
    selected_file_ids: list[str]
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


def create_drive_mounts_router(
    *,
    provider_factory: DriveProviderFactory,
    credential_vault: SourceCredentialVault,
    connection_credential_lookup: DriveConnectionCredentialLookup,
    mount_connection_lookup: DriveConnectionLookup | None = None,
    tracking_scope_store,
    mount_creation_callback: DriveMountCreationCallback,
    initial_change_sync: DriveInitialChangeSync | None = None,
    connection_authz_dependency: AuthzDependency = deny_all_authz,
    mount_authz_dependency: AuthzDependency = deny_all_authz,
    workspace_authz_dependency: AuthzDependency = deny_all_authz,
) -> APIRouter:
    router = APIRouter()

    async def initialize_selection(
        *, mount_id: str, selected_file_ids: list[str]
    ) -> None:
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
            selected_file_ids=body.selected_file_ids,
        )

        await tracking_scope_store.save(
            result.server_mount_id,
            DriveTrackingScope(
                mount_id=result.server_mount_id,
                selected_file_ids=result.selected_file_ids or body.selected_file_ids,
                display_metadata_by_file=_selected_metadata(
                    body.display_metadata_by_file,
                    result.selected_file_ids or body.selected_file_ids,
                ),
            ),
        )

        await initialize_selection(
            mount_id=result.server_mount_id,
            selected_file_ids=result.selected_file_ids or body.selected_file_ids,
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
            selected_file_ids=body.selected_file_ids,
        )
        await tracking_scope_store.save(
            result.server_mount_id,
            DriveTrackingScope(
                mount_id=result.server_mount_id,
                selected_file_ids=result.selected_file_ids or body.selected_file_ids,
                display_metadata_by_file=_selected_metadata(
                    body.display_metadata_by_file,
                    result.selected_file_ids or body.selected_file_ids,
                ),
            ),
        )
        await initialize_selection(
            mount_id=result.server_mount_id,
            selected_file_ids=result.selected_file_ids or body.selected_file_ids,
        )
        return result

    return router


def _selected_metadata(
    metadata: dict[str, SafeMetadata], selected_file_ids: list[str]
) -> dict[str, SafeMetadata]:
    return {
        file_id: metadata[file_id]
        for file_id in selected_file_ids
        if file_id in metadata
    }
