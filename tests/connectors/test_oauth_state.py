from __future__ import annotations

import asyncio
import time

from ip_risk_agent.connectors.common.oauth_state import InMemoryOAuthStateStore, generate_state


def test_generate_state_produces_unique_values():
    values = {generate_state() for _ in range(100)}
    assert len(values) == 100


def test_save_then_consume_returns_context():
    async def scenario():
        store = InMemoryOAuthStateStore()
        await store.save("state-1", {"risk_workspace_id": "rw1"})
        context = await store.consume("state-1")
        assert context == {"risk_workspace_id": "rw1"}

    asyncio.run(scenario())


def test_consume_is_single_use():
    async def scenario():
        store = InMemoryOAuthStateStore()
        await store.save("state-1", {"risk_workspace_id": "rw1"})
        await store.consume("state-1")
        second = await store.consume("state-1")
        assert second is None

    asyncio.run(scenario())


def test_consume_unknown_state_returns_none():
    async def scenario():
        store = InMemoryOAuthStateStore()
        result = await store.consume("never-saved")
        assert result is None

    asyncio.run(scenario())


def test_expired_state_returns_none():
    async def scenario():
        store = InMemoryOAuthStateStore(ttl_seconds=0)
        await store.save("state-1", {"risk_workspace_id": "rw1"})
        time.sleep(0.05)
        result = await store.consume("state-1")
        assert result is None

    asyncio.run(scenario())
