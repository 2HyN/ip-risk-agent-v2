from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.oauth_state import InMemoryOAuthStateStore
from ip_risk_agent.connectors.common.authz import allow_all_authz
from ip_risk_agent.connectors.github.install_routes import create_github_install_router
from ip_risk_agent.composition.source_completion import ProductSourceCompletionRedirect


class FakeConnectionCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_github_connection(self, request: Request, *, risk_workspace_id, installation_id) -> str:
        self.calls.append({"risk_workspace_id": risk_workspace_id, "installation_id": installation_id})
        return "conn-1"


def _build_client(completion_redirect=None):
    state_store = InMemoryOAuthStateStore()
    callback = FakeConnectionCreationCallback()
    router = create_github_install_router(
        app_slug="ip-risk-agent",
        state_store=state_store,
        connection_creation_callback=callback,
        authz_dependency=allow_all_authz,
        completion_redirect=completion_redirect,
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


def test_callback_redirect_contains_only_product_completion_identifiers():
    client, _, _ = _build_client(
        completion_redirect=ProductSourceCompletionRedirect("https://app.example.com")
    )
    state = client.post(
        "/api/v1/source-connections/github/install/start",
        json={"risk_workspace_id": "rw1"},
    ).json()["state"]

    response = client.get(
        "/api/v1/source-connections/github/install/callback",
        params={"installation_id": "12345", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "https://app.example.com/w/rw1/sources?"
        "provider=GITHUB&connection_id=conn-1&status=connected"
    )
    assert "12345" not in response.headers["location"]


def test_callback_with_invalid_state_returns_400():
    client, _, callback = _build_client()

    response = client.get(
        "/api/v1/source-connections/github/install/callback",
        params={"installation_id": "12345", "state": "never-issued"},
    )

    assert response.status_code == 400
    assert callback.calls == []
    # 무엇을 다시 해야 하는지 말해 주지 않으면 사용자가 같은 실패를 반복한다.
    # 승인 화면을 오래 붙들거나 뒤로가기로 옛 URL 을 다시 열면 여기로 온다.
    detail = response.json()["detail"]
    assert detail["code"] == "OAUTH_STATE_EXPIRED"
    assert "다시 시작" in detail["message"]


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
