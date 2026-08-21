from __future__ import annotations

import json
import logging
from typing import Protocol

from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from iprisk_contracts.common import SafeMetadata

from ..common.authz import AuthzDependency, allow_all_authz
from ..common.credential_vault import SourceCredentialVault
from ..common.errors import NotFoundError, SourceConnectorError
from .connection_lookup import DriveConnectionCredentialLookup
from .tracking_scope import DriveTrackingScope

logger = logging.getLogger(__name__)


class DriveProviderFactory(Protocol):
    def create(self, token: dict) -> object: ...


class SelectionExpander(Protocol):
    """Picker 선택에서 폴더를 하위 파일로 펼친다.

    사용자는 폴더를 "폴더 안을 감시해 달라"는 뜻으로 고르지만, 변경 감지는
    file id 정확 일치다. 펼치지 않으면 그 기대가 조용히 어긋난다.
    """

    async def expand(
        self, connection_id: str, selected_file_ids: list[str]
    ) -> Sequence: ...


class InitialScan(Protocol):
    """확장된 파일들을 분석 파이프라인에 넣는다 (기존 파일 초기 분석)."""

    async def __call__(
        self,
        *,
        risk_workspace_id: str,
        mount_id: str,
        source_workspace_id: str,
        files: Sequence,
    ) -> int: ...


class PickerSessionResponse(BaseModel):
    access_token: str
    # Google Picker 를 브라우저에서 여는 데 필요한 공개 설정. 없으면 화면이
    # Picker 를 열 수 없다는 사실을 사용자에게 정확히 알려야 한다.
    api_key: str | None = None
    app_id: str | None = None


class DriveMountCreationRequest(BaseModel):
    risk_workspace_id: str
    selected_file_ids: list[str]
    display_metadata_by_file: dict[str, SafeMetadata] = {}


class DriveMountCreationResponse(BaseModel):
    server_mount_id: str
    source_workspace_id: str


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


def create_drive_mounts_router(
    *,
    provider_factory: DriveProviderFactory,
    credential_vault: SourceCredentialVault,
    connection_credential_lookup: DriveConnectionCredentialLookup,
    tracking_scope_store,
    mount_creation_callback: DriveMountCreationCallback,
    authz_dependency: AuthzDependency = allow_all_authz,
    picker_api_key: str | None = None,
    picker_app_id: str | None = None,
    selection_expander: SelectionExpander | None = None,
    initial_scan: InitialScan | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/source-connections/{connection_id}/drive/picker-session",
        response_model=PickerSessionResponse,
    )
    async def create_picker_session(connection_id: str, request: Request) -> PickerSessionResponse:
        await authz_dependency(request, connection_id)

        try:
            credential_ref = await connection_credential_lookup.resolve_credential_ref(connection_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown source connection") from exc

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

        return PickerSessionResponse(
            access_token=access_token,
            api_key=picker_api_key,
            app_id=picker_app_id,
        )

    @router.post(
        "/api/v1/source-connections/{connection_id}/drive/mounts",
        response_model=DriveMountCreationResponse,
    )
    async def create_mount(
        connection_id: str, request: Request, body: DriveMountCreationRequest
    ) -> DriveMountCreationResponse:
        await authz_dependency(request, body.risk_workspace_id)

        selected_file_ids = body.selected_file_ids
        display_metadata = dict(body.display_metadata_by_file)
        files: Sequence = ()
        if selection_expander is not None:
            files = await selection_expander.expand(
                connection_id, body.selected_file_ids
            )
            selected_file_ids = [f.file_id for f in files]
            for f in files:
                # 경로가 이름을 이긴다. 폴더마다 있는 같은 이름의 파일을
                # 이름만으로는 구분할 수 없다.
                display_metadata[f.file_id] = {
                    **display_metadata.get(f.file_id, {}),
                    "name": f.path,
                }
            if not selected_file_ids:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "선택한 폴더에 접근 가능한 파일이 없습니다. "
                        "파일이 든 폴더나 파일을 골라 주세요."
                    ),
                )

        result = await mount_creation_callback.create_drive_mount(
            request,
            connection_id=connection_id,
            risk_workspace_id=body.risk_workspace_id,
            selected_file_ids=selected_file_ids,
        )

        await tracking_scope_store.save(
            result.server_mount_id,
            DriveTrackingScope(
                mount_id=result.server_mount_id,
                # 펼친 목록을 저장해야 변경 감지(file id 일치)가 폴더 안의
                # 파일들과 실제로 맞는다.
                selected_file_ids=selected_file_ids,
                display_metadata_by_file=display_metadata,
            ),
        )

        if initial_scan is not None and files:
            # 이미 있던 파일에는 변경 이벤트가 오지 않는다. 여기서 파이프라인에
            # 넣지 않으면 "기획서가 있는데 위험이 안 뜨는" 상태가 된다.
            # Mount 는 이미 만들어진 사실이므로 스캔 실패가 생성 성공을
            # 실패로 둔갑시키면 안 된다.
            try:
                await initial_scan(
                    risk_workspace_id=body.risk_workspace_id,
                    mount_id=result.server_mount_id,
                    source_workspace_id=result.source_workspace_id,
                    files=files,
                )
            except Exception:
                logger.exception(
                    "drive initial scan failed (mount=%s)", result.server_mount_id
                )

        return result

    return router
