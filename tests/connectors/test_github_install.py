from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.oauth_state import InMemoryOAuthStateStore
from ip_risk_agent.connectors.common.authz import allow_all_authz
from ip_risk_agent.connectors.github.install_routes import create_github_install_router


class FakeConnectionCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_github_connection(self, request: Request, *, risk_workspace_id, installation_id) -> str:
        self.calls.append({"risk_workspace_id": risk_workspace_id, "installation_id": installation_id})
        return "conn-1"


def _build_client():
    state_store = InMemoryOAuthStateStore()
    callback = FakeConnectionCreationCallback()
    router = create_github_install_router(
        app_slug="ip-risk-agent",
        state_store=state_store,
        connection_creation_callback=callback,
        authz_dependency=allow_all_authz,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, state_store, callback


def test_start_returns_install_url_with_state():
    client, _, _ = _build_client()

    response = client.post(
        "/api/v1/source-connections/github/install/start", json={"risk_workspace_id": "rw1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert "github.com/apps/ip-risk-agent/installations/new" in body["authorize_url"]
    assert body["state"] in body["authorize_url"]


def test_callback_with_valid_state_creates_connection():
    client, _, callback = _build_client()

    start_resp = client.post(
        "/api/v1/source-connections/github/install/start", json={"risk_workspace_id": "rw1"}
    )
    state = start_resp.json()["state"]

    response = client.get(
        "/api/v1/source-connections/github/install/callback",
        params={"installation_id": "12345", "state": state},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connection_id"] == "conn-1"
    assert body["installation_id"] == "12345"
    assert callback.calls == [{"risk_workspace_id": "rw1", "installation_id": "12345"}]


def test_callback_with_invalid_state_returns_400():
    client, _, callback = _build_client()

    response = client.get(
        "/api/v1/source-connections/github/install/callback",
        params={"installation_id": "12345", "state": "never-issued"},
    )

    assert response.status_code == 400
    assert callback.calls == []


def test_callback_state_cannot_be_reused():
    client, _, _ = _build_client()

    start_resp = client.post(
        "/api/v1/source-connections/github/install/start", json={"risk_workspace_id": "rw1"}
    )
    state = start_resp.json()["state"]

    first = client.get(
        "/api/v1/source-connections/github/install/callback",
        params={"installation_id": "12345", "state": state},
    )
    second = client.get(
        "/api/v1/source-connections/github/install/callback",
        params={"installation_id": "99999", "state": state},
    )

    assert first.status_code == 200
    assert second.status_code == 400
