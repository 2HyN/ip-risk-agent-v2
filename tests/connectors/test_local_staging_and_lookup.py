from __future__ import annotations

import asyncio

import pytest

from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.local.device_lookup import (
    InMemoryLocalDeviceLookup,
    LocalDeviceContext,
)
from ip_risk_agent.connectors.local.staging_store import InMemoryLocalStagingStore, StagingRef


def test_staging_put_then_get_roundtrip():
    async def scenario():
        store = InMemoryLocalStagingStore()
        ref = await store.put("hello world", {})
        assert await store.get(ref) == "hello world"

    asyncio.run(scenario())


def test_staging_get_missing_raises_not_found():
    async def scenario():
        store = InMemoryLocalStagingStore()
        with pytest.raises(NotFoundError):
            await store.get(StagingRef(object_name="never-existed"))

    asyncio.run(scenario())


def test_staging_delete_then_get_raises_not_found():
    async def scenario():
        store = InMemoryLocalStagingStore()
        ref = await store.put("content", {})
        await store.delete(ref)
        with pytest.raises(NotFoundError):
            await store.get(ref)

    asyncio.run(scenario())


def test_device_lookup_register_then_resolve():
    async def scenario():
        lookup = InMemoryLocalDeviceLookup()
        lookup.register("mount-1", LocalDeviceContext(device_id="dev-1", mount_handle="handle-1"))
        resolved = await lookup.resolve("mount-1")
        assert resolved.device_id == "dev-1"

    asyncio.run(scenario())


def test_device_lookup_unknown_raises_not_found():
    async def scenario():
        lookup = InMemoryLocalDeviceLookup()
        with pytest.raises(NotFoundError):
            await lookup.resolve("never-registered")

    asyncio.run(scenario())
