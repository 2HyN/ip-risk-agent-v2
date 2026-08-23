from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.credential_vault import (
    CredentialScope,
    InMemoryCredentialVault,
)
from ip_risk_agent.connectors.common.authz import allow_all_authz, deny_all_authz
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.google_drive.connection_lookup import (
    DriveConnectionContext,
    InMemoryDriveConnectionLookup,
    InMemoryDriveConnectionCredentialLookup,
)
from ip_risk_agent.connectors.google_drive.mounts_routes import (
    DriveMountCreationResponse,
    create_drive_mounts_router,
)

from iprisk_contracts.common import SourceType


class FakeDriveProvider:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.export_called = False

    def get_access_token(self):
        if self.should_fail:
            from ip_risk_agent.connectors.common.errors import AuthRequiredError

            raise AuthRequiredError(provider="google_drive", safe_message="reauth required")
        return ("refreshed-access-token", None)

    def export_token(self) -> dict:
        self.export_called = True
        return {"access_token": "refreshed-access-token", "refresh_token": "rt", "expires_at": None, "scope": "x"}


class FakeDriveProviderFactory:
    def __init__(self, provider: FakeDriveProvider) -> None:
        self._provider = provider

    def create(self, token: dict) -> FakeDriveProvider:
        return self._provider


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
        return DriveMountCreationResponse(server_mount_id="server-mount-1", source_workspace_id="sw-1")


class FakeInitialChangeSync:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def initialize(self, *, mount_id, selected_file_ids) -> None:
        self.calls.append(
            {"mount_id": mount_id, "selected_file_ids": selected_file_ids}
        )


class FailingInitialChangeSync:
    async def initialize(self, *, mount_id, selected_file_ids) -> None:
        from ip_risk_agent.connectors.common.errors import TemporaryUnavailableError

        raise TemporaryUnavailableError(
            provider="google_drive",
            safe_message="drive_file_metadata failed",
            retryable=False,
        )


async def _setup(
    provider: FakeDriveProvider | None = None,
    *,
    mount_authz=allow_all_authz,
    workspace_authz=allow_all_authz,
    initial_change_sync=None,
    untrack_callback=None,
):
    vault = InMemoryCredentialVault()
    cred_scope = CredentialScope(provider=SourceType.GOOGLE_DRIVE, connection_id="conn-1", secret_name="tok")
    token_json = json.dumps({"access_token": "at", "refresh_token": "rt", "expires_at": None, "scope": "x"})
    credential_ref = await vault.put(cred_scope, token_json)

    lookup = InMemoryDriveConnectionCredentialLookup()
    lookup.register("conn-1", credential_ref)
    mount_lookup = InMemoryDriveConnectionLookup()
    mount_lookup.register(
        "mount-1",
        DriveConnectionContext(
            connection_id="canonical-conn-1",
            credential_ref=credential_ref,
            operational_connection_id="conn-1",
        ),
    )

    tracking_scope_store = InMemoryRuntimeStore()
    callback = FakeMountCreationCallback()
    factory = FakeDriveProviderFactory(provider or FakeDriveProvider())

    router = create_drive_mounts_router(
        provider_factory=factory,
        credential_vault=vault,
        connection_credential_lookup=lookup,
        mount_connection_lookup=mount_lookup,
        tracking_scope_store=tracking_scope_store,
        mount_creation_callback=callback,
        untrack_callback=untrack_callback,
        initial_change_sync=initial_change_sync,
        connection_authz_dependency=allow_all_authz,
        mount_authz_dependency=mount_authz,
        workspace_authz_dependency=workspace_authz,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, vault, tracking_scope_store, callback, credential_ref


def test_picker_session_returns_access_token():
    async def scenario():
        client, vault, _, _, _ = await _setup()

        response = client.post("/api/v1/source-connections/conn-1/drive/picker-session")

        assert response.status_code == 200
        assert response.json()["access_token"] == "refreshed-access-token"

    asyncio.run(scenario())


def test_picker_session_persists_refreshed_token():
    async def scenario():
        client, vault, _, _, credential_ref = await _setup()

        client.post("/api/v1/source-connections/conn-1/drive/picker-session")

        stored = await vault.get(credential_ref)
        assert "refreshed-access-token" in stored

    asyncio.run(scenario())


def test_picker_session_unknown_connection_returns_error():
    async def scenario():
        client, _, _, _, _ = await _setup()

        response = client.post("/api/v1/source-connections/never-registered/drive/picker-session")

        assert response.status_code >= 400

    asyncio.run(scenario())


def test_picker_session_reauth_required_returns_401():
    async def scenario():
        client, _, _, _, _ = await _setup(FakeDriveProvider(should_fail=True))

        response = client.post("/api/v1/source-connections/conn-1/drive/picker-session")

        assert response.status_code == 401

    asyncio.run(scenario())


def test_create_mount_saves_tracking_scope_and_calls_callback():
    async def scenario():
        client, _, tracking_scope_store, callback, _ = await _setup()

        response = client.post(
            "/api/v1/source-connections/conn-1/drive/mounts",
            json={
                "risk_workspace_id": "rw1",
                "folder_id": "folder-1",
                "display_metadata_by_file": {"file-1": {"name": "architecture.docx"}},
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["server_mount_id"] == "server-mount-1"
        assert callback.calls[0]["selected_file_ids"] == ["folder-1"]

        scope = await tracking_scope_store.load("server-mount-1")
        assert scope.folder_id == "folder-1"

    asyncio.run(scenario())


def test_create_mount_publishes_initial_changes_after_tracking_scope_is_saved():
    async def scenario():
        sync = FakeInitialChangeSync()
        client, _, tracking_scope_store, _, _ = await _setup(
            initial_change_sync=sync
        )

        response = client.post(
            "/api/v1/source-connections/conn-1/drive/mounts",
            json={
                "risk_workspace_id": "rw1",
                "folder_id": "folder-1",
            },
        )

        assert response.status_code == 200
        assert await tracking_scope_store.load("server-mount-1") is not None
        # 처음 훑기는 **폴더가 정한다.** 부르는 쪽이 목록을 주지 않는다 (§6.1 · 1-F).
        assert sync.calls == [{
            "mount_id": "server-mount-1",
            "selected_file_ids": None,
        }]

    asyncio.run(scenario())


def test_provider_method_error_is_a_safe_gateway_error_not_422():
    async def scenario():
        client, _, tracking_scope_store, _, _ = await _setup(
            initial_change_sync=FailingInitialChangeSync()
        )

        response = client.post(
            "/api/v1/source-mounts/mount-1/drive/mounts",
            json={"risk_workspace_id": "rw1", "folder_id": "folder-1"},
        )

        assert response.status_code == 502
        assert response.json() == {
            "detail": {
                "code": "DRIVE_INITIAL_SYNC_FAILED",
                "operation": "drive_file_metadata",
                "provider_error": "TEMPORARY_UNAVAILABLE",
                "retryable": False,
            }
        }
        assert await tracking_scope_store.load("server-mount-1") is not None
        assert "file-3" not in response.text

    asyncio.run(scenario())


def test_active_mount_reuses_credential_and_operational_connection_for_more_files():
    async def scenario():
        client, _, tracking_scope_store, callback, _ = await _setup()

        picker = client.post("/api/v1/source-mounts/mount-1/drive/picker-session")
        mounted = client.post(
            "/api/v1/source-mounts/mount-1/drive/mounts",
            json={"risk_workspace_id": "rw1", "folder_id": "folder-1"},
        )

        assert picker.status_code == 200
        assert mounted.status_code == 200
        assert callback.calls[-1] == {
            "connection_id": "conn-1",
            "risk_workspace_id": "rw1",
            "selected_file_ids": ["folder-1"],
        }
        scope = await tracking_scope_store.load("server-mount-1")
        assert scope.folder_id == "folder-1"

    asyncio.run(scenario())


def test_mount_route_method_mismatch_is_405_not_422():
    async def scenario():
        client, _, _, _, _ = await _setup()

        response = client.get("/api/v1/source-mounts/mount-1/drive/mounts")

        assert response.status_code == 405
        assert response.json() == {"detail": "Method Not Allowed"}

    asyncio.run(scenario())


def test_active_mount_rejects_an_unauthorized_workspace_before_credential_use():
    async def deny(_request, _resource_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="source operation denied")

    async def scenario():
        client, _, _, callback, _ = await _setup(workspace_authz=deny)

        response = client.post(
            "/api/v1/source-mounts/mount-1/drive/mounts",
            json={"risk_workspace_id": "other-workspace", "folder_id": "folder-1"},
        )

        assert response.status_code == 403
        assert callback.calls == []

    asyncio.run(scenario())


class FakeUntrackCallback:
    """canonical 쪽 처리를 대신한다. 실제 구현은 artifact 를 보관하고 Risk 를 제외한다."""

    def __init__(self, *, mount_id: str, source_artifact_id: str) -> None:
        self.calls: list[tuple[str, str]] = []
        self._mount_id = mount_id
        self._source_artifact_id = source_artifact_id

    async def untrack_artifact(self, request, *, risk_workspace_id, artifact_id):
        del request
        self.calls.append((risk_workspace_id, artifact_id))

        class _Outcome:
            mount_id = self._mount_id
            source_artifact_id = self._source_artifact_id
            excluded_risk_ids = ("risk-1",)

        return _Outcome()


def test_the_untrack_route_is_gone():
    """폴더를 보는 지금 "이 파일만 추적 해제" 는 성립하지 않는다 (§6.1 · 1-F).

    범위에서 뺄 방법이 없고, Risk 만 닫아 두면 **그 파일의 다음 변경에 되살아난다.**
    추적을 끊는 방법은 하나뿐이다 — 폴더 밖으로 옮긴다. 실측에서 그것이 `removed`
    로 오고(§2.1.1), 1-D 가 그때 Risk 를 닫는다.
    """

    async def scenario():
        client, _vault, _tracking, _create, _ref = await _setup()
        response = client.post(
            "/api/v1/source-mounts/mount-1/drive/untrack",
            json={"risk_workspace_id": "vws-1", "artifact_id": "artifact-1"},
        )
        assert response.status_code == 404

    asyncio.run(scenario())
