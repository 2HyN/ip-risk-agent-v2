"""runtime_store.py의 모델/저장소를 확인한다."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ip_risk_agent.connectors.common.runtime_store import (
    DriveRuntime,
    GitHubRuntime,
    InMemoryRuntimeStore,
    LocalConnectionStatus,
    LocalRuntime,
    WebhookStatus,
)


def test_drive_runtime_minimal_construction():
    runtime = DriveRuntime(connection_id="conn-1")
    assert runtime.change_cursor is None
    assert runtime.watch_channel_id is None


def test_github_runtime_minimal_construction():
    runtime = GitHubRuntime(
        connection_id="conn-1",
        installation_id="inst-1",
        repository_id="repo-1",
        tracked_branch="main",
    )
    assert runtime.webhook_status is WebhookStatus.INACTIVE
    assert runtime.last_seen_delivery_id is None


def test_local_runtime_minimal_construction():
    runtime = LocalRuntime(device_id="dev-1", mount_handle="mount-1")
    assert runtime.status is LocalConnectionStatus.UNKNOWN
    assert runtime.staging_metadata == {}


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        DriveRuntime(connection_id="conn-1", not_a_real_field="oops")  # type: ignore[call-arg]


def test_drive_runtime_full_fields():
    now = datetime.now(timezone.utc)
    runtime = DriveRuntime(
        connection_id="conn-1",
        change_cursor="cursor-abc",
        watch_channel_id="chan-1",
        watch_resource_id="res-1",
        watch_expiry=now,
        reconciliation_lease="lease-1",
    )
    assert runtime.watch_expiry == now


def test_inmemory_store_roundtrip_drive():
    async def scenario() -> None:
        store: InMemoryRuntimeStore[DriveRuntime] = InMemoryRuntimeStore()
        runtime = DriveRuntime(connection_id="conn-1", change_cursor="c1")

        await store.save("conn-1", runtime)
        loaded = await store.load("conn-1")

        assert loaded is not None
        assert loaded.change_cursor == "c1"

    asyncio.run(scenario())


def test_inmemory_store_roundtrip_github():
    async def scenario() -> None:
        store: InMemoryRuntimeStore[GitHubRuntime] = InMemoryRuntimeStore()
        runtime = GitHubRuntime(
            connection_id="conn-1",
            installation_id="inst-1",
            repository_id="repo-1",
            tracked_branch="main",
        )
        key = "inst-1:repo-1"

        await store.save(key, runtime)
        loaded = await store.load(key)

        assert loaded is not None
        assert loaded.repository_id == "repo-1"

    asyncio.run(scenario())


def test_inmemory_store_missing_key_returns_none():
    async def scenario() -> None:
        store: InMemoryRuntimeStore[LocalRuntime] = InMemoryRuntimeStore()
        loaded = await store.load("never-saved")
        assert loaded is None

    asyncio.run(scenario())


def test_inmemory_store_delete_then_load_returns_none():
    async def scenario() -> None:
        store: InMemoryRuntimeStore[LocalRuntime] = InMemoryRuntimeStore()
        runtime = LocalRuntime(device_id="dev-1", mount_handle="mount-1")

        await store.save("dev-1", runtime)
        await store.delete("dev-1")
        loaded = await store.load("dev-1")

        assert loaded is None

    asyncio.run(scenario())


def test_inmemory_store_keys_are_isolated():
    async def scenario() -> None:
        store: InMemoryRuntimeStore[DriveRuntime] = InMemoryRuntimeStore()
        a = DriveRuntime(connection_id="a", change_cursor="cursor-a")
        b = DriveRuntime(connection_id="b", change_cursor="cursor-b")

        await store.save("a", a)
        await store.save("b", b)

        loaded_a = await store.load("a")
        loaded_b = await store.load("b")

        assert loaded_a is not None and loaded_a.change_cursor == "cursor-a"
        assert loaded_b is not None and loaded_b.change_cursor == "cursor-b"

    asyncio.run(scenario())
