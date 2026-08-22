from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.change_sink import InMemorySourceChangeSink
from ip_risk_agent.connectors.common.authz import allow_all_authz
from ip_risk_agent.connectors.local.routes import (
    MountRegistrationResponse,
    create_local_desktop_router,
)
from ip_risk_agent.connectors.local.staging_store import InMemoryLocalStagingStore


class FakeDeviceRegistrationCallback:
    def __init__(self) -> None:
        self.registered: list[tuple[str, str]] = []

    async def register_device(self, request: Request, device_id: str, device_label: str) -> None:
        self.registered.append((device_id, device_label))


class FakeMountCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_id = 1

    async def create_local_mount(self, request: Request, body) -> MountRegistrationResponse:
        self.calls.append(body.model_dump())
        result = MountRegistrationResponse(
            server_mount_id=f"server-mount-{self.next_id}",
            source_workspace_id=f"sw-{self.next_id}",
        )
        self.next_id += 1
        return result


def _build_client(authz_dependency=allow_all_authz):
    staging_store = InMemoryLocalStagingStore()
    sink = InMemorySourceChangeSink()
    device_cb = FakeDeviceRegistrationCallback()
    mount_cb = FakeMountCreationCallback()
    kwargs = {
        "staging_store": staging_store,
        "change_sink": sink,
        "device_registration_callback": device_cb,
        "mount_creation_callback": mount_cb,
    }
    kwargs["device_registration_authz_dependency"] = authz_dependency
    kwargs["workspace_authz_dependency"] = authz_dependency
    kwargs["mount_authz_dependency"] = authz_dependency
    router = create_local_desktop_router(**kwargs)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, staging_store, sink, device_cb, mount_cb


def test_staging_upload_returns_object_name_and_stores_content():
    from ip_risk_agent.connectors.local.staging_store import StagingRef

    client, staging_store, _, _, _ = _build_client()

    response = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})

    assert response.status_code == 200
    object_name = response.json()["object_name"]
    assert object_name

    async def check():
        stored = await staging_store.get(StagingRef(object_name=object_name))
        assert stored == "print(1)"

    asyncio.run(check())


def test_event_with_staging_creates_change():
    async def scenario():
        client, staging_store, sink, _, _ = _build_client()

        upload_resp = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})
        object_name = upload_resp.json()["object_name"]

        event_resp = client.post(
            "/desktop/events",
            json={
                "risk_workspace_id": "rw1",
                "mount_id": "mount-1",
                "source_workspace_id": "sw1",
                "device_id": "dev-1",
                "relative_path": "src/main.py",
                "change_type": "UPDATE",
                "revision": "rev-1",
                "staging_object_name": object_name,
            },
        )

        assert event_resp.status_code == 200
        assert len(sink.received) == 1

    asyncio.run(scenario())


def test_delete_event_does_not_require_staging_object():
    client, _, sink, _, _ = _build_client()

    response = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/gone.py",
            "change_type": "DELETE",
        },
    )

    assert response.status_code == 200
    assert sink.received[0].change_type.value == "DELETE"


def test_non_delete_event_without_staging_returns_400():
    client, _, sink, _, _ = _build_client()

    response = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/main.py",
            "change_type": "UPDATE",
        },
    )

    assert response.status_code == 400
    assert sink.received == []


def test_event_fingerprint_is_deterministic_for_same_input():
    client, _, sink, _, _ = _build_client()

    body = {
        "risk_workspace_id": "rw1",
        "mount_id": "mount-1",
        "source_workspace_id": "sw1",
        "device_id": "dev-1",
        "relative_path": "src/gone.py",
        "change_type": "DELETE",
    }
    r1 = client.post("/desktop/events", json=body)
    r2 = client.post("/desktop/events", json=body)

    assert r1.json()["event_id"] == r2.json()["event_id"]


def test_move_event_creates_previous_artifact():
    client, _, sink, _, _ = _build_client()

    upload_resp = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print('moved')"})
    object_name = upload_resp.json()["object_name"]

    response = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/new_name.py",
            "change_type": "MOVE",
            "staging_object_name": object_name,
            "previous_relative_path": "src/old_name.py",
        },
    )

    assert response.status_code == 200
    change = sink.received[0]
    assert change.change_type.value == "MOVE"
    assert change.previous_artifact is not None


def test_move_event_without_previous_path_returns_400():
    client, _, sink, _, _ = _build_client()

    upload_resp = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})
    object_name = upload_resp.json()["object_name"]

    response = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/new_name.py",
            "change_type": "MOVE",
            "staging_object_name": object_name,
        },
    )

    assert response.status_code == 400
    assert sink.received == []


def test_default_authz_allows_all_requests():
    client, _, sink, _, _ = _build_client()

    response = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/gone.py",
            "change_type": "DELETE",
        },
    )

    assert response.status_code == 200
    assert len(sink.received) == 1


def test_custom_authz_dependency_can_reject_requests():
    async def deny_mount_2(request: Request, resource_id: str) -> None:
        if resource_id == "mount-2":
            raise HTTPException(status_code=403, detail="not authorized for this mount")

    client, _, sink, _, _ = _build_client(authz_dependency=deny_mount_2)

    allowed = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1", "mount_id": "mount-1", "source_workspace_id": "sw1",
            "device_id": "dev-1", "relative_path": "src/gone.py", "change_type": "DELETE",
        },
    )
    denied = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1", "mount_id": "mount-2", "source_workspace_id": "sw1",
            "device_id": "dev-1", "relative_path": "src/gone.py", "change_type": "DELETE",
        },
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403


def test_custom_authz_dependency_applies_to_staging_too():
    async def deny_all(request: Request, resource_id: str) -> None:
        raise HTTPException(status_code=403, detail="denied")

    client, _, _, _, _ = _build_client(authz_dependency=deny_all)

    response = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})

    assert response.status_code == 403


def test_device_registration_calls_callback():
    client, _, _, device_cb, _ = _build_client()

    response = client.post(
        "/desktop/devices/register", json={"device_id": "dev-1", "device_label": "Alice-MacBook"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert device_cb.registered == [("dev-1", "Alice-MacBook")]


def test_mount_registration_returns_server_ids_from_callback():
    client, _, _, _, mount_cb = _build_client()

    response = client.post(
        "/desktop/mounts/register",
        json={
            "risk_workspace_id": "rw1",
            "device_id": "dev-1",
            "include_patterns": ["**/*.py"],
            "exclude_patterns": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["server_mount_id"] == "server-mount-1"
    assert body["source_workspace_id"] == "sw-1"
    assert len(mount_cb.calls) == 1
    assert mount_cb.calls[0]["risk_workspace_id"] == "rw1"


def test_mount_registration_does_not_accept_canonical_root_path_field():
    # canonical_root_path는 애초에 요청 스키마에 없다 (§25) — extra field로
    # 보내도 조용히 무시되는지(스키마에 없다는 사실 자체) 확인한다.
    client, _, _, _, mount_cb = _build_client()

    response = client.post(
        "/desktop/mounts/register",
        json={
            "risk_workspace_id": "rw1",
            "device_id": "dev-1",
            "canonical_root_path": "/Users/alice/secret-project",
        },
    )

    assert response.status_code == 200
    assert "canonical_root_path" not in mount_cb.calls[0]


def test_mount_registration_authz_uses_risk_workspace_id():
    seen: list[str] = []

    async def record_authz(request: Request, resource_id: str) -> None:
        seen.append(resource_id)

    client, _, _, _, _ = _build_client(authz_dependency=record_authz)

    client.post(
        "/desktop/mounts/register",
        json={"risk_workspace_id": "rw-target", "device_id": "dev-1"},
    )

    assert seen == ["rw-target"]


def test_every_change_carries_a_revision_even_without_one_from_the_device():
    """판본이 비면 intake 가 변경 자체를 거절한다.

    가짜 sink 는 그 검증을 하지 않으므로 라우트 시험만으로는 드러나지 않았다.
    실제로는 데스크톱이 보낸 이벤트가 전부 422 로 죽었고
    (`source_change.revision-must-not-be-empty`), 폴더를 연결해도 파일이 하나도
    보이지 않았다. 그래서 라우트가 **무엇을 내놓는지**를 직접 본다.
    """
    client, _staging, sink, _, _ = _build_client()

    upload = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})
    created = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/main.py",
            "change_type": "UPDATE",
            "staging_object_name": upload.json()["object_name"],
        },
    )
    deleted = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/gone.py",
            "change_type": "DELETE",
        },
    )

    assert created.status_code == 200
    assert deleted.status_code == 200
    for change in sink.received:
        assert change.revision, f"{change.change_type} 이 판본 없이 나갔다"


def test_the_device_revision_is_used_when_it_sends_one():
    """기기는 내용 해시를 보낸다. 같은 내용이면 같은 판본이어야 중복이 걸러진다."""
    client, _staging, sink, _, _ = _build_client()

    upload = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})
    client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-1",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/main.py",
            "change_type": "UPDATE",
            "revision": "sha256-of-content",
            "staging_object_name": upload.json()["object_name"],
        },
    )

    assert sink.received[-1].revision == "sha256-of-content"
