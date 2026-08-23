from __future__ import annotations

import json
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from iprisk_contracts.common import SafeMetadata

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.errors import (
    NotFoundError,
    PermissionDeniedError,
    SourceConnectorError,
)
from .folders import list_folder_files
from .models import FOLDER_MIME_TYPE
from .tracking_scope import DriveTrackingScope


class DriveProviderFactory(Protocol):
    """D1 — 토큰 없이 만든다. 신원이 하나뿐이다."""

    def create(self) -> object: ...


class DriveSharingAddressResponse(BaseModel):
    """이 주소로 폴더를 공유하면 그 안이 보인다.

    Picker 를 대신한다. Picker 의 폴더 선택은 **폴더 객체만** 주었고 안은 못 읽었다
    (결함 41). 서비스 계정은 사람과 같은 방식으로 공유받으므로 폴더가 폴더로 보인다.
    """

    address: str


def parse_folder_reference(raw: str) -> str:
    """붙여 넣은 것에서 폴더 id 를 꺼낸다.

    사용자가 손에 들고 있는 것은 주소창의 URL 이다. id 만 꺼내 오라고 요구하면
    거기서부터 틀린다. 맨 id 도 그대로 받는다.
    """
    value = (raw or "").strip()
    if not value:
        raise ValueError("folder reference is empty")
    if "://" in value:
        without_query = value.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in without_query.split("/") if p]
        for marker in ("folders", "d"):
            if marker in parts:
                index = parts.index(marker)
                if index + 1 < len(parts):
                    return parts[index + 1]
        if parts:
            return parts[-1]
        raise ValueError("folder reference has no id")
    return value


class DriveMountCreationRequest(BaseModel):
    """공유받은 **폴더 하나**를 붙인다 (§6.1 · 1-F).

    예전에는 고른 file id 의 목록을 받았다. 그러면 마운트한 뒤에 폴더에 넣은 파일이
    영영 잡히지 않는다 — 이 서비스를 쓰는 방법이 바로 그 "넣는 것" 이다.
    """

    risk_workspace_id: str
    #: 폴더 id 또는 Drive 주소창 URL. 사용자가 손에 든 것을 그대로 받는다.
    folder_id: str = Field(min_length=1, max_length=2048)
    display_metadata_by_file: dict[str, SafeMetadata] = {}


class DriveMountCreationResponse(BaseModel):
    server_mount_id: str
    source_workspace_id: str
    selected_file_ids: list[str] = Field(default_factory=list)
    #: 붙인 직후 폴더에서 실제로 찾은 파일 수. **0 도 답이다** — 화면이 "비어
    #: 있다" 와 "못 읽는다" 를 구별하려면 이 값이 있어야 한다 (결함 40).
    tracked_file_count: int | None = None
    #: 상한(항목 300 · 깊이 10)에 걸려 멈췄는가. 조용히 자르지 않는다.
    truncated: bool = False


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


class DriveConnectionCreationCallback(Protocol):
    """Control 의 canonical SourceConnection 생성.

    D1 에서는 넘길 자격증명이 없다. `credential_ref` 가 `None` 인 것이 정상이고,
    그것이 이 결정이 없애려던 바로 그 보관물이다.
    """

    async def create_drive_connection(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        provider_subject: str,
        provider_email: str,
        credential_ref: object | None,
    ) -> str: ...


class DriveInitialChangeSync(Protocol):
    async def initialize(
        self, *, mount_id: str, selected_file_ids: list[str]
    ) -> None: ...


def create_drive_mounts_router(
    *,
    provider_factory: DriveProviderFactory,
    sharing_address: str,
    connection_creation_callback: DriveConnectionCreationCallback,
    tracking_scope_store,
    mount_creation_callback: DriveMountCreationCallback,
    initial_change_sync: DriveInitialChangeSync | None = None,
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

    def inspect_folder(folder_reference: str):
        """붙이기 **전에** 세 가지를 확정한다.

        1. 공유가 됐는가 — 안 됐으면 Google 이 거절한다. 봉쇄가 우리 밖에 있다.
        2. **폴더인가** — 파일을 폴더로 받으면 아무것도 추적하지 않는 마운트가
           성공으로 보인다 (결함 37).
        3. 안에 몇 개가 있는가 — 0 을 0 이라고 말할 수 있어야 한다 (결함 40).
        """
        try:
            folder_id = parse_folder_reference(folder_reference)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "DRIVE_FOLDER_REFERENCE_INVALID",
                    "message": "Drive 폴더 주소 또는 폴더 id 를 넣어 주세요.",
                },
            ) from exc

        provider = provider_factory.create()
        try:
            metadata = provider.get_file(folder_id)
        except (NotFoundError, PermissionDeniedError) as exc:
            # 아직 공유가 안 됐다. 이것이 가장 흔한 첫 실패이므로 무엇을 해야
            # 하는지를 그대로 돌려준다.
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DRIVE_FOLDER_NOT_SHARED",
                    "sharing_address": sharing_address,
                    "message": (
                        "이 폴더가 아직 공유되지 않았습니다. Drive 에서 폴더를 열고 "
                        f"{sharing_address} 를 뷰어로 공유한 뒤 다시 시도해 주세요."
                    ),
                },
            ) from exc
        except SourceConnectorError as exc:
            raise HTTPException(
                status_code=503 if exc.retryable else 502,
                detail={
                    "code": "DRIVE_FOLDER_LOOKUP_FAILED",
                    "provider_error": exc.category.value,
                    "retryable": exc.retryable,
                },
            ) from exc

        if metadata.mime_type != FOLDER_MIME_TYPE:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "DRIVE_NOT_A_FOLDER",
                    "message": (
                        "폴더가 아니라 파일입니다. 추적할 파일들을 담은 **폴더**를 "
                        "공유하고 그 폴더 주소를 넣어 주세요."
                    ),
                },
            )

        try:
            listing = list_folder_files(provider, folder_id)
        except SourceConnectorError as exc:
            raise HTTPException(
                status_code=503 if exc.retryable else 502,
                detail={
                    "code": "DRIVE_FOLDER_LISTING_FAILED",
                    "provider_error": exc.category.value,
                    "retryable": exc.retryable,
                },
            ) from exc
        return folder_id, metadata, listing

    @router.get(
        "/api/v1/source-connections/google-drive/sharing-address",
        response_model=DriveSharingAddressResponse,
    )
    async def read_sharing_address() -> DriveSharingAddressResponse:
        """공유할 주소는 비밀이 아니다.

        이것을 알아도 접근이 생기지 않는다 — 접근은 **사용자가 공유해야** 생긴다.
        그래서 인증 뒤에 두지 않고, 연결을 시작하기 전에 보여줄 수 있게 한다.
        """
        return DriveSharingAddressResponse(address=sharing_address)

    @router.post(
        "/api/v1/source-connections/google-drive/folders",
        response_model=DriveMountCreationResponse,
    )
    async def mount_shared_folder(
        request: Request, body: DriveMountCreationRequest
    ) -> DriveMountCreationResponse:
        """공유받은 폴더 하나를 붙인다 — 이것이 D1 의 전부다.

        OAuth 승인도 Picker 도 없다. 사용자가 폴더를 서비스 계정에 공유하고 그 주소를
        넣으면 끝이다. 보관할 자격증명이 생기지 않는다.

        **확인을 먼저 하고 만든다.** 아무것도 못 읽는 마운트를 만들어 놓고 나중에
        조용히 0 개를 돌려주는 것이 결함 37 · 41 이 함께 만든 실패였다.
        """
        await workspace_authz_dependency(request, body.risk_workspace_id)

        folder_id, metadata, listing = inspect_folder(body.folder_id)

        # 연결을 마운트마다 새로 만든다. 변경 커서와 감시 채널이 연결 id 로 보관되고,
        # 폴더마다 자기 커서를 가져야 한 폴더의 대조가 다른 폴더의 변경을 삼키지
        # 않는다.
        connection_id = await connection_creation_callback.create_drive_connection(
            request,
            risk_workspace_id=body.risk_workspace_id,
            provider_subject=sharing_address,
            provider_email=sharing_address,
            credential_ref=None,
        )

        result = await mount_creation_callback.create_drive_mount(
            request,
            connection_id=connection_id,
            risk_workspace_id=body.risk_workspace_id,
            selected_file_ids=[folder_id],
        )

        display_metadata = dict(body.display_metadata_by_file)
        display_metadata.setdefault(folder_id, SafeMetadata({"name": metadata.name}))
        await _set_tracked_folder(
            tracking_scope_store,
            mount_id=result.server_mount_id,
            folder_id=folder_id,
            display_metadata_by_file=display_metadata,
        )

        await initialize_selection(
            mount_id=result.server_mount_id, selected_file_ids=None
        )

        return result.model_copy(
            update={
                "tracked_file_count": len(listing.files),
                "truncated": listing.truncated,
            }
        )

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
