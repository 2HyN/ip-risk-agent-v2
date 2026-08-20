from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.change_sink import InMemorySourceChangeSink
from ip_risk_agent.connectors.local.routes import create_local_desktop_router
from ip_risk_agent.connectors.local.staging_store import InMemoryLocalStagingStore


def _build_client(authz_dependency=None):
    staging_store = InMemoryLocalStagingStore()
    sink = InMemorySourceChangeSink()
    kwargs = {"staging_store": staging_store, "change_sink": sink}
    if authz_dependency is not None:
        kwargs["authz_dependency"] = authz_dependency
    router = create_local_desktop_router(**kwargs)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, staging_store, sink


def test_staging_upload_returns_object_name_and_stores_content():
    from ip_risk_agent.connectors.local.staging_store import StagingRef

    client, staging_store, _ = _build_client()

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
        client, staging_store, sink = _build_client()

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
        change = sink.received[0]
        assert change.artifact.display_name == "main.py"
        assert change.safe_metadata["staging_object_name"] == object_name

    asyncio.run(scenario())


def test_delete_event_does_not_require_staging_object():
    client, _, sink = _build_client()

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
    client, _, sink = _build_client()

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
    client, _, sink = _build_client()

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
    client, _, sink = _build_client()

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
    assert change.artifact.display_name == "new_name.py"
    assert change.previous_artifact is not None
    assert change.previous_artifact.display_name == "old_name.py"


def test_move_event_without_previous_path_returns_400():
    client, _, sink = _build_client()

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
    client, _, sink = _build_client()

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
    calls: list[tuple[str, str]] = []

    async def deny_mount_2(request: Request, mount_id: str) -> None:
        calls.append((request.url.path, mount_id))
        if mount_id == "mount-2":
            raise HTTPException(status_code=403, detail="not authorized for this mount")

    client, _, sink = _build_client(authz_dependency=deny_mount_2)

    allowed = client.post(
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
    denied = client.post(
        "/desktop/events",
        json={
            "risk_workspace_id": "rw1",
            "mount_id": "mount-2",
            "source_workspace_id": "sw1",
            "device_id": "dev-1",
            "relative_path": "src/gone.py",
            "change_type": "DELETE",
        },
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert len(sink.received) == 1
    assert ("/desktop/events", "mount-1") in calls
    assert ("/desktop/events", "mount-2") in calls


def test_custom_authz_dependency_applies_to_staging_too():
    async def deny_all(request: Request, mount_id: str) -> None:
        raise HTTPException(status_code=403, detail="denied")

    client, _, _ = _build_client(authz_dependency=deny_all)

    response = client.post("/desktop/staging", json={"mount_id": "mount-1", "content": "print(1)"})

    assert response.status_code == 403
