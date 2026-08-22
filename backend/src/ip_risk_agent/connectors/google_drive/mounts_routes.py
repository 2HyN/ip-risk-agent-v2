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

        await _merge_tracking_scope(
            tracking_scope_store,
            mount_id=result.server_mount_id,
            added_file_ids=result.selected_file_ids or body.selected_file_ids,
            display_metadata_by_file=body.display_metadata_by_file,
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
        await _merge_tracking_scope(
            tracking_scope_store,
            mount_id=result.server_mount_id,
            added_file_ids=result.selected_file_ids or body.selected_file_ids,
            display_metadata_by_file=body.display_metadata_by_file,
        )
        await initialize_selection(
            mount_id=result.server_mount_id,
            selected_file_ids=result.selected_file_ids or body.selected_file_ids,
        )
        return result

    @router.post(
        "/api/v1/source-mounts/{mount_id}/drive/untrack",
        response_model=DriveUntrackResponse,
    )
    async def untrack_drive_artifact(
        mount_id: str, request: Request, body: DriveUntrackRequest
    ) -> DriveUntrackResponse:
        await mount_authz_dependency(request, mount_id)
        await workspace_authz_dependency(request, body.risk_workspace_id)
        if untrack_callback is None:
            raise HTTPException(status_code=404, detail="untracking is not configured")
        outcome = await untrack_callback.untrack_artifact(
            request,
            risk_workspace_id=body.risk_workspace_id,
            artifact_id=body.artifact_id,
        )
        # canonical 처리가 끝난 뒤에 감시를 끊는다. 순서를 뒤집으면 canonical 처리가
        # 실패했을 때 감시만 끊긴 채로 Risk 가 활성으로 남는다. 이 순서라면 반대로
        # 감시가 남아 다음 변경에 Risk 가 되살아나므로 사용자가 다시 시도할 수 있다.
        remaining = await _remove_from_tracking_scope(
            tracking_scope_store,
            mount_id=outcome.mount_id,
            file_id=outcome.source_artifact_id,
        )
        return DriveUntrackResponse(
            artifact_id=body.artifact_id,
            excluded_risk_ids=list(outcome.excluded_risk_ids),
            remaining_file_count=remaining,
        )

    return router


async def _remove_from_tracking_scope(
    tracking_scope_store,
    *,
    mount_id: str,
    file_id: str,
) -> int:
    """추적 범위에서 file id 하나를 뺀다. 남은 개수를 돌려준다.

    범위에 없으면 아무것도 바꾸지 않는다. 같은 파일을 두 번 해제해도 안전하다.
    """
    existing: DriveTrackingScope | None = await tracking_scope_store.load(mount_id)
    if existing is None:
        return 0
    if file_id not in existing.selected_file_ids:
        return len(existing.selected_file_ids)
    file_ids = [item for item in existing.selected_file_ids if item != file_id]
    metadata = {
        key: value
        for key, value in existing.display_metadata_by_file.items()
        if key != file_id
    }
    await tracking_scope_store.save(
        mount_id,
        DriveTrackingScope(
            mount_id=mount_id,
            selected_file_ids=file_ids,
            display_metadata_by_file=metadata,
        ),
    )
    return len(file_ids)


async def _merge_tracking_scope(
    tracking_scope_store,
    *,
    mount_id: str,
    added_file_ids: list[str],
    display_metadata_by_file: dict[str, SafeMetadata],
) -> None:
    """추적 범위에 새 선택을 **더한다**.

    Drive source workspace 는 계정 단위로 하나이므로 mount 도 하나다. 이번에 새로
    고른 file id 만 저장하면 이전에 추적하던 파일이 감시 대상에서 사라진다.
    변경 감지는 이 범위 안의 file id 로만 동작하므로, 덮어쓰면 조용히 감시가 끊긴다.
    """
    existing: DriveTrackingScope | None = await tracking_scope_store.load(mount_id)
    file_ids = list(existing.selected_file_ids) if existing is not None else []
    metadata = dict(existing.display_metadata_by_file) if existing is not None else {}
    for file_id in added_file_ids:
        if file_id not in file_ids:
            file_ids.append(file_id)
    metadata.update(_selected_metadata(display_metadata_by_file, added_file_ids))
    await tracking_scope_store.save(
        mount_id,
        DriveTrackingScope(
            mount_id=mount_id,
            selected_file_ids=file_ids,
            display_metadata_by_file=metadata,
        ),
    )


def _selected_metadata(
    metadata: dict[str, SafeMetadata], selected_file_ids: list[str]
) -> dict[str, SafeMetadata]:
    return {
        file_id: metadata[file_id]
        for file_id in selected_file_ids
        if file_id in metadata
    }
