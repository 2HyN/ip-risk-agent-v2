from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from iprisk_contracts.common import ChangeType, MountRef, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange

from ip_risk_agent.connectors.common.errors import NotFoundError, UnsupportedContentError
from ip_risk_agent.connectors.common.runtime_store import (
    InMemoryRuntimeStore,
    LocalConnectionStatus,
    LocalRuntime,
)
from ip_risk_agent.connectors.local.adapter import LocalAdapter
from ip_risk_agent.connectors.local.device_lookup import (
    InMemoryLocalDeviceLookup,
    LocalDeviceContext,
)
from ip_risk_agent.connectors.local.identity import encode_local_artifact_id
from ip_risk_agent.connectors.local.staging_store import InMemoryLocalStagingStore


def _mount() -> MountRef:
    return MountRef(
        risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1",
        source_type=SourceType.LOCAL,
    )


def _change(
    *,
    change_type: ChangeType = ChangeType.UPDATE,
    staging_object_name: str | None = "staging-1",
    revision: str | None = "rev-1",
    display_name: str = "search.py",
) -> SourceChange:
    artifact_id = encode_local_artifact_id(device_id="dev-1", mount_id="mount-1", relative_path="src/search.py")
    safe_metadata = {"staging_object_name": staging_object_name} if staging_object_name else {}
    return SourceChange(
        contract_version="1", event_id="e1", event_fingerprint="fp1",
        risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1",
        source_type=SourceType.LOCAL,
        artifact=SourceArtifactRef(source_artifact_id=artifact_id, display_name=display_name, path_hint="src/search.py"),
        change_type=change_type, revision=revision,
        observed_at=datetime.now(timezone.utc), safe_metadata=safe_metadata,
    )


async def _build_adapter(*, device_registered: bool = True, runtime_status: LocalConnectionStatus | None = LocalConnectionStatus.ONLINE):
    staging_store = InMemoryLocalStagingStore()
    device_lookup = InMemoryLocalDeviceLookup()
    runtime_store = InMemoryRuntimeStore()

    if device_registered:
        device_lookup.register("mount-1", LocalDeviceContext(device_id="dev-1", mount_handle="handle-1"))
        if runtime_status is not None:
            await runtime_store.save("dev-1", LocalRuntime(device_id="dev-1", mount_handle="handle-1", status=runtime_status))

    adapter = LocalAdapter(staging_store=staging_store, device_lookup=device_lookup, runtime_store=runtime_store)
    return adapter, staging_store


def test_fetch_snapshot_returns_full_text_from_staging():
    async def scenario():
        adapter, staging_store = await _build_adapter()
        ref = await staging_store.put("def search(): pass", {})
        change = _change(staging_object_name=ref.object_name)

        snapshot = await adapter.fetch_snapshot(change)

        assert snapshot.content_scope.value == "FULL_TEXT"
        assert snapshot.text_segments[0].text == "def search(): pass"
        assert snapshot.artifact_kind.value == "SOURCE_CODE"

    asyncio.run(scenario())


def test_cleanup_deletes_staging_object_only_after_terminal_pipeline_signal():
    async def scenario():
        adapter, staging_store = await _build_adapter()
        ref = await staging_store.put("content", {})
        change = _change(staging_object_name=ref.object_name)

        await adapter.fetch_snapshot(change)

        assert await staging_store.get(ref) == "content"
        await adapter.cleanup(change)

        with pytest.raises(NotFoundError):
            await staging_store.get(ref)

    asyncio.run(scenario())


def test_fetch_snapshot_delete_change_returns_unsupported_without_staging():
    async def scenario():
        adapter, _ = await _build_adapter()
        change = _change(change_type=ChangeType.DELETE, staging_object_name=None)

        snapshot = await adapter.fetch_snapshot(change)

        assert snapshot.content_scope.value == "UNSUPPORTED"
        assert snapshot.text_segments == []

    asyncio.run(scenario())


def test_fetch_snapshot_missing_staging_ref_raises_unsupported_content():
    async def scenario():
        adapter, _ = await _build_adapter()
        change = _change(staging_object_name=None)

        with pytest.raises(UnsupportedContentError):
            await adapter.fetch_snapshot(change)

    asyncio.run(scenario())


def test_resolve_original_decodes_device_id():
    async def scenario():
        adapter, _ = await _build_adapter()
        artifact_id = encode_local_artifact_id(device_id="dev-42", mount_id="mount-1", relative_path="a.py")

        locator = await adapter.resolve_original(SourceArtifactRef(source_artifact_id=artifact_id, display_name="a.py"))

        assert locator.original_source_type.value == "LOCAL_DEVICE"
        assert locator.device_id == "dev-42"
        assert locator.provider_url is None

    asyncio.run(scenario())


def test_health_healthy_when_device_online():
    async def scenario():
        adapter, _ = await _build_adapter(runtime_status=LocalConnectionStatus.ONLINE)
        health = await adapter.health(_mount())
        assert health.status.value == "HEALTHY"

    asyncio.run(scenario())


def test_health_offline_when_device_status_offline():
    async def scenario():
        adapter, _ = await _build_adapter(runtime_status=LocalConnectionStatus.OFFLINE)
        health = await adapter.health(_mount())
        assert health.status.value == "OFFLINE"

    asyncio.run(scenario())


def test_health_offline_when_device_not_registered():
    async def scenario():
        adapter, _ = await _build_adapter(device_registered=False)
        health = await adapter.health(_mount())
        assert health.status.value == "OFFLINE"

    asyncio.run(scenario())


def test_reconcile_is_safe_no_op():
    async def scenario():
        adapter, _ = await _build_adapter()
        result = await adapter.reconcile(_mount(), cursor="whatever")
        assert result.changes == []
        assert result.has_more is False
        assert result.next_cursor == "whatever"

    asyncio.run(scenario())
