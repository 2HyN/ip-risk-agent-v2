from __future__ import annotations

import time

import jwt
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.credential_vault import CredentialRef, InMemoryCredentialVault
from ip_risk_agent.connectors.common.oauth_state import InMemoryOAuthStateStore
from ip_risk_agent.connectors.google_drive.oauth_routes import create_drive_oauth_router


def _fake_id_token(sub: str, email: str) -> str:
    return jwt.encode({"sub": sub, "email": email, "iat": int(time.time())}, "test-secret", algorithm="HS256")


class FakeDriveOAuthClient:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.exchanged_codes: list[str] = []

    async def exchange_code(self, code: str) -> dict:
        self.exchanged_codes.append(code)
        if self.should_fail:
            from ip_risk_agent.connectors.common.errors import AuthRequiredError

            raise AuthRequiredError(provider="google_drive", safe_message="bad code")
        return {
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "scope": "openid email https://www.googleapis.com/auth/drive.file",
            "id_token": _fake_id_token("google-subject-1", "research@company.com"),
        }


class FakeConnectionCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_drive_connection(
        self, request: Request, *, risk_workspace_id, provider_subject, provider_email, credential_ref
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


def _build_client(oauth_client=None):
    state_store = InMemoryOAuthStateStore()
    vault = InMemoryCredentialVault()
    callback = FakeConnectionCreationCallback()
    router = create_drive_oauth_router(
        client_id="test-client-id",
        redirect_uri="https://app.example.com/callback",
        state_store=state_store,
        oauth_client=oauth_client or FakeDriveOAuthClient(),
        credential_vault=vault,
        connection_creation_callback=callback,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, state_store, vault, callback


def test_start_returns_authorize_url_with_state():
    client, _, _, _ = _build_client()

    response = client.post("/api/v1/source-connections/google-drive/start", json={"risk_workspace_id": "rw1"})

    assert response.status_code == 200
    body = response.json()
    assert "accounts.google.com" in body["authorize_url"]
    assert body["state"] in body["authorize_url"]
    assert "drive.file" in body["authorize_url"]


def test_callback_with_valid_state_exchanges_code_and_creates_connection():
    client, _, vault, callback = _build_client()

    start_resp = client.post(
        "/api/v1/source-connections/google-drive/start", json={"risk_workspace_id": "rw1"}
    )
    state = start_resp.json()["state"]

    callback_resp = client.get(
        "/api/v1/source-connections/google-drive/callback", params={"code": "auth-code-1", "state": state}
    )

    assert callback_resp.status_code == 200
    body = callback_resp.json()
    assert body["connection_id"] == "conn-1"
    assert body["provider_email"] == "research@company.com"
    assert len(callback.calls) == 1
    assert callback.calls[0]["risk_workspace_id"] == "rw1"
    assert callback.calls[0]["provider_subject"] == "google-subject-1"


def test_callback_with_invalid_state_returns_400():
    client, _, _, callback = _build_client()

    response = client.get(
        "/api/v1/source-connections/google-drive/callback",
        params={"code": "auth-code-1", "state": "never-issued-state"},
    )

    assert response.status_code == 400
    assert callback.calls == []


def test_callback_state_cannot_be_reused():
    client, _, _, _ = _build_client()

    start_resp = client.post(
        "/api/v1/source-connections/google-drive/start", json={"risk_workspace_id": "rw1"}
    )
    state = start_resp.json()["state"]

    first = client.get(
        "/api/v1/source-connections/google-drive/callback", params={"code": "auth-code-1", "state": state}
    )
    second = client.get(
        "/api/v1/source-connections/google-drive/callback", params={"code": "auth-code-2", "state": state}
    )

    assert first.status_code == 200
    assert second.status_code == 400


def test_callback_stores_refresh_token_in_vault():
    client, _, vault, callback = _build_client()

    start_resp = client.post(
        "/api/v1/source-connections/google-drive/start", json={"risk_workspace_id": "rw1"}
    )
    state = start_resp.json()["state"]
    client.get(
        "/api/v1/source-connections/google-drive/callback", params={"code": "auth-code-1", "state": state}
    )

    credential_ref: CredentialRef = callback.calls[0]["credential_ref"]

    import asyncio

    async def check():
        secret = await vault.get(credential_ref)
        assert "rt-456" in secret

    asyncio.run(check())


def test_exchange_failure_does_not_create_connection():
    client, _, _, callback = _build_client(oauth_client=FakeDriveOAuthClient(should_fail=True))

    start_resp = client.post(
        "/api/v1/source-connections/google-drive/start", json={"risk_workspace_id": "rw1"}
    )
    state = start_resp.json()["state"]

    response = client.get(
        "/api/v1/source-connections/google-drive/callback", params={"code": "bad-code", "state": state}
    )

    assert response.status_code >= 400
    assert callback.calls == []
