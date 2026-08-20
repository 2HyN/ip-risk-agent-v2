from __future__ import annotations

import asyncio

import httpx
import pytest

from ip_risk_agent.connectors.common.errors import TemporaryUnavailableError
from ip_risk_agent.connectors.google_drive.oauth import HttpxDriveOAuthClient


def test_real_drive_oauth_client_retries_on_500_then_succeeds(monkeypatch):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt"})

    original_async_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_async_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    async def scenario():
        client = HttpxDriveOAuthClient(
            client_id="cid", client_secret="secret", redirect_uri="https://app.example.com/cb"
        )
        result = await client.exchange_code("auth-code")
        assert result["access_token"] == "at"

    asyncio.run(scenario())
    assert call_count == 2


def test_real_drive_oauth_client_does_not_retry_on_400(monkeypatch):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json={"error": "invalid_grant"})

    original_async_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_async_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    async def scenario():
        client = HttpxDriveOAuthClient(
            client_id="cid", client_secret="secret", redirect_uri="https://app.example.com/cb"
        )
        with pytest.raises(TemporaryUnavailableError):
            await client.exchange_code("bad-code")

    asyncio.run(scenario())
    assert call_count == 1
