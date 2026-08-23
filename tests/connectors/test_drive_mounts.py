"""D1 — 폴더를 공유받아 붙인다. 승인 화면도 Picker 도 없다.

예전 시험은 Picker 세션 발급과 연결별 마운트를 확인했다. 그 경로는 **동작하지
않는 것으로 실측됐다** — `drive.file` 로 폴더를 고르면 폴더 객체만 받고 안은 못
읽는다 (결함 41). 그래서 확인할 것이 바뀌었다.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.authz import allow_all_authz, deny_all_authz
from ip_risk_agent.connectors.common.errors import (
    NotFoundError,
    PermissionDeniedError,
    TemporaryUnavailableError,
)
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.google_drive.models import DriveFile, DriveFolderPage
from ip_risk_agent.connectors.google_drive.mounts_routes import (
    DriveMountCreationResponse,
    create_drive_mounts_router,
    parse_folder_reference,
)

SHARING_ADDRESS = "iprisk-v2-drive@example.iam.gserviceaccount.com"
FOLDER_ID = "folder-1"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOCUMENT_MIME = "application/vnd.google-apps.document"


def _folder(file_id: str = FOLDER_ID, name: str = "patent") -> DriveFile:
    return DriveFile(file_id, name, FOLDER_MIME, "t1", "rev-1", None, ())


def _doc(file_id: str, name: str) -> DriveFile:
    return DriveFile(file_id, name, "text/plain", "t1", "rev-1", None, (FOLDER_ID,))


class FakeDriveProvider:
    def __init__(
        self,
        *,
        root: DriveFile | None = None,
        children: tuple[DriveFile, ...] = (),
        lookup_error: Exception | None = None,
    ) -> None:
        self._root = root if root is not None else _folder()
        self._children = children
        self._lookup_error = lookup_error
        self.export_called = False

    def get_file(self, file_id: str) -> DriveFile:
        if self._lookup_error is not None:
            raise self._lookup_error
        return self._root

    def list_folder_children(self, folder_id: str, page_token: str | None = None):
        return DriveFolderPage(files=self._children, next_page_token=None)

    def export_token(self) -> dict:
        self.export_called = True
        return {}


class FakeDriveProviderFactory:
    def __init__(self, provider: FakeDriveProvider) -> None:
        self._provider = provider

    def create(self) -> FakeDriveProvider:
        return self._provider


class FakeConnectionCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_drive_connection(
        self,
        request: Request,
        *,
        risk_workspace_id,
        provider_subject,
        provider_email,
        credential_ref,
    ) -> str:
        self.calls.append(
            {
                "risk_workspace_id": risk_workspace_id,
                "provider_subject": provider_subject,
                "provider_email": provider_email,
                "credential_ref": credential_ref,
            }
        )
        return "conn-1"


class FakeMountCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_drive_mount(
        self, request: Request, *, connection_id, risk_workspace_id, selected_file_ids
    ) -> DriveMountCreationResponse:
        self.calls.append(
            {
                "connection_id": connection_id,
                "risk_workspace_id": risk_workspace_id,
                "selected_file_ids": selected_file_ids,
            }
        )
        return DriveMountCreationResponse(
            server_mount_id="server-mount-1", source_workspace_id="sw-1"
        )


class FakeInitialChangeSync:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def initialize(self, *, mount_id, selected_file_ids) -> None:
        self.calls.append({"mount_id": mount_id, "selected_file_ids": selected_file_ids})


class FailingInitialChangeSync:
    async def initialize(self, *, mount_id, selected_file_ids) -> None:
        raise TemporaryUnavailableError(
            provider="google_drive",
            safe_message="drive_file_metadata failed",
            retryable=False,
        )


def _setup(
    provider: FakeDriveProvider,
    *,
    workspace_authz=allow_all_authz,
    initial_change_sync=None,
):
    tracking_scope_store = InMemoryRuntimeStore()
    connections = FakeConnectionCreationCallback()
    mounts = FakeMountCreationCallback()
    sync = initial_change_sync if initial_change_sync is not None else FakeInitialChangeSync()

    router = create_drive_mounts_router(
        provider_factory=FakeDriveProviderFactory(provider),
        sharing_address=SHARING_ADDRESS,
        connection_creation_callback=connections,
        tracking_scope_store=tracking_scope_store,
        mount_creation_callback=mounts,
        initial_change_sync=sync,
        workspace_authz_dependency=workspace_authz,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), tracking_scope_store, connections, mounts, sync


def _mount(client, folder_reference: str = FOLDER_ID):
    return client.post(
        "/api/v1/source-connections/google-drive/folders",
        json={"risk_workspace_id": "vws-1", "folder_id": folder_reference},
    )


def test_the_sharing_address_is_what_the_screen_shows_instead_of_a_picker():
    client, *_ = _setup(FakeDriveProvider())
    response = client.get("/api/v1/source-connections/google-drive/sharing-address")
    assert response.status_code == 200
    assert response.json() == {"address": SHARING_ADDRESS}


def test_a_shared_folder_is_mounted_and_reports_how_many_files_it_found():
    """0 을 0 이라고 말할 수 있어야 한다 (결함 40).

    개수를 돌려주지 않으면 화면에서 빈 폴더와 못 읽는 폴더가 똑같이 아무것도 아닌
    것으로 보인다. 실제로 사용자가 그 둘을 구별하지 못해 파일을 폴더로 골랐다.
    """
    provider = FakeDriveProvider(children=(_doc("f1", "a.md"), _doc("f2", "b.md")))
    client, scopes, _connections, mounts, sync = _setup(provider)

    response = _mount(client)

    assert response.status_code == 200
    body = response.json()
    assert body["tracked_file_count"] == 2
    assert body["truncated"] is False

    scope = asyncio.run(scopes.load("server-mount-1"))
    assert scope.folder_id == FOLDER_ID
    assert scope.display_metadata_by_file[FOLDER_ID]["name"] == "patent"
    assert mounts.calls[0]["selected_file_ids"] == [FOLDER_ID]
    assert sync.calls == [{"mount_id": "server-mount-1", "selected_file_ids": None}]


def test_an_empty_shared_folder_is_a_success_that_says_zero():
    client, *_ = _setup(FakeDriveProvider(children=()))

    response = _mount(client)

    assert response.status_code == 200
    assert response.json()["tracked_file_count"] == 0


def test_the_connection_carries_no_credential_because_there_is_nothing_to_keep():
    """D1 의 요점 — 보관할 자격증명이 없다.

    workspace 를 전부 지운 뒤에도 Drive refresh token 19 개가 남아 있던 사고가
    구조적으로 재발할 수 없는 이유가 이것이다.
    """
    client, _scopes, connections, _mounts, _sync = _setup(FakeDriveProvider())

    _mount(client)

    assert connections.calls[0]["credential_ref"] is None
    # 연결의 정체성은 **폴더**다. 서비스 계정 주소로 잡으면 한 워크스페이스의 모든
    # Drive 폴더가 연결 하나로 접히고, 변경 커서를 나눠 쓰다 서로의 변경을 삼킨다.
    assert connections.calls[0]["provider_subject"] == FOLDER_ID
    # 화면에 보이는 것은 폴더 이름이다. 주소를 alias 로 쓰면 목록에 같은 긴 주소만
    # 늘어서고 어느 폴더인지 알 수 없다.
    assert connections.calls[0]["provider_email"] == "patent"


def test_a_file_is_refused_instead_of_becoming_a_mount_that_tracks_nothing():
    """결함 37 — 파일을 폴더로 받으면 아무것도 안 하는 마운트가 성공으로 보인다.

    운영에서 실제로 그렇게 됐다. Google 문서 하나가 folder_id 로 들어가, 부모로
    건 질의가 영영 0 개인 ACTIVE 마운트가 만들어졌다.
    """
    document = DriveFile("doc-1", "문서", DOCUMENT_MIME, "t1", "r1", None, ())
    client, _scopes, connections, mounts, _sync = _setup(FakeDriveProvider(root=document))

    response = _mount(client, "doc-1")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "DRIVE_NOT_A_FOLDER"
    # 아무것도 만들지 않는다. 확인이 먼저다.
    assert connections.calls == []
    assert mounts.calls == []


def test_an_unshared_folder_is_told_exactly_what_to_do():
    client, _scopes, connections, mounts, _sync = _setup(
        FakeDriveProvider(
            lookup_error=NotFoundError(provider="google_drive", safe_message="not found")
        )
    )

    response = _mount(client)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "DRIVE_FOLDER_NOT_SHARED"
    assert detail["sharing_address"] == SHARING_ADDRESS
    assert connections.calls == []
    assert mounts.calls == []


def test_a_folder_we_may_not_read_is_the_same_answer_as_one_never_shared():
    client, *_ = _setup(
        FakeDriveProvider(
            lookup_error=PermissionDeniedError(
                provider="google_drive", safe_message="denied"
            )
        )
    )
    assert _mount(client).status_code == 409


def test_a_provider_failure_is_a_safe_gateway_error_not_a_422():
    client, *_ = _setup(
        FakeDriveProvider(
            lookup_error=TemporaryUnavailableError(
                provider="google_drive", safe_message="drive is busy", retryable=True
            )
        )
    )

    response = _mount(client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DRIVE_FOLDER_LOOKUP_FAILED"


def test_a_failed_initial_sweep_does_not_report_a_mounted_folder():
    client, *_ = _setup(
        FakeDriveProvider(children=(_doc("f1", "a.md"),)),
        initial_change_sync=FailingInitialChangeSync(),
    )

    response = _mount(client)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "DRIVE_INITIAL_SYNC_FAILED"


def test_an_unauthorized_workspace_is_refused_before_drive_is_touched():
    client, _scopes, connections, mounts, _sync = _setup(
        FakeDriveProvider(), workspace_authz=deny_all_authz
    )

    response = _mount(client)

    assert response.status_code == 401
    assert connections.calls == []
    assert mounts.calls == []


def test_the_untrack_route_is_gone():
    """폴더를 보는 지금 파일 하나만 해제하는 것은 성립하지 않는다 (§6.1 · 1-F)."""
    client, *_ = _setup(FakeDriveProvider())
    response = client.post(
        "/api/v1/source-mounts/mount-1/drive/untrack",
        json={"risk_workspace_id": "vws-1", "artifact_id": "artifact-1"},
    )
    assert response.status_code == 404


def test_the_picker_session_route_is_gone():
    """Picker 는 폴더 객체만 주었다. 그 경로를 남겨 두면 다시 그리로 간다."""
    client, *_ = _setup(FakeDriveProvider())
    response = client.post("/api/v1/source-connections/conn-1/drive/picker-session")
    assert response.status_code == 404


def test_a_pasted_drive_url_is_accepted_because_that_is_what_users_hold():
    assert parse_folder_reference("folder-1") == "folder-1"
    assert (
        parse_folder_reference("https://drive.google.com/drive/folders/abc123?usp=sharing")
        == "abc123"
    )
    assert parse_folder_reference("  https://drive.google.com/drive/u/0/folders/xyz  ") == "xyz"


def test_two_folders_in_one_workspace_are_two_connections_not_one():
    """폴더마다 자기 연결을 갖는다.

    D1 이 신원을 서비스 계정 하나로 바꾸면서, 예전에 마운트를 갈라 주던 값(연결된
    Drive 계정)이 **모든 폴더에 대해 같아졌다.** 연결을 그 값으로 잡으면 한
    워크스페이스의 Drive 폴더가 전부 하나로 접히고, 두 번째 폴더를 붙이는 순간
    첫 폴더가 추적 범위에서 조용히 덮어써진다.
    """
    first = _folder("folder-1", "patent")
    second = _folder("folder-2", "design")
    provider = FakeDriveProvider(root=first)
    client, _scopes, connections, _mounts, _sync = _setup(provider)

    _mount(client, "folder-1")
    provider._root = second
    _mount(client, "folder-2")

    assert [call["provider_subject"] for call in connections.calls] == ["folder-1", "folder-2"]
    assert [call["provider_email"] for call in connections.calls] == ["patent", "design"]
