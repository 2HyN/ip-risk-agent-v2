from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from iprisk_contracts.common import ChangeType, MountRef, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange

from ip_risk_agent.connectors.common.credential_vault import (
    CredentialScope,
    InMemoryCredentialVault,
)
from ip_risk_agent.connectors.common.errors import PermissionDeniedError
from ip_risk_agent.connectors.google_drive.adapter import GoogleDriveAdapter
from ip_risk_agent.connectors.google_drive.connection_lookup import (
    DriveConnectionContext,
    InMemoryDriveConnectionLookup,
)
from ip_risk_agent.connectors.google_drive.models import DriveFile
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore


class FakeDriveProvider:
    def __init__(self, files: dict, texts: dict) -> None:
        self._files = files
        self._texts = texts
        self.export_called = False

    def get_access_token(self):
        return ("fake-token", None)

    def get_file(self, file_id: str) -> DriveFile:
        return self._files[file_id]

    def get_start_page_token(self) -> str:
        return "start-1"

    def create_google_doc(self, name: str):
        raise NotImplementedError

    def list_changes(self, page_token: str):
        raise NotImplementedError

    def read_text(self, file_id: str, mime_type: str) -> str:
        return self._texts[file_id]

    def export_token(self) -> dict:
        self.export_called = True
        return {"access_token": "refreshed", "refresh_token": "rt", "expires_at": None, "scope": "x"}


class FakeDriveProviderFactory:
    def __init__(self, provider: FakeDriveProvider) -> None:
        self._provider = provider

    def create(self, token: dict) -> FakeDriveProvider:
        return self._provider


async def _build_adapter(provider: FakeDriveProvider, *, tracked_ids: list[str]):
    vault = InMemoryCredentialVault()
    lookup = InMemoryDriveConnectionLookup()
    scope_store = InMemoryRuntimeStore()

    cred_scope = CredentialScope(provider=SourceType.GOOGLE_DRIVE, connection_id="conn-1", secret_name="tok")
    token_json = json.dumps({"access_token": "at", "refresh_token": "rt", "expires_at": None, "scope": "x"})
    ref = await vault.put(cred_scope, token_json)
    lookup.register("mount-1", DriveConnectionContext(connection_id="conn-1", credential_ref=ref))

    await scope_store.save(
        "mount-1",
        DriveTrackingScope(mount_id="mount-1", selected_file_ids=tracked_ids, display_metadata_by_file={}),
    )

    adapter = GoogleDriveAdapter(
        provider_factory=FakeDriveProviderFactory(provider),
        credential_vault=vault,
        connection_lookup=lookup,
        tracking_scope_store=scope_store,
    )
    return adapter, vault, ref


def _mount() -> MountRef:
    return MountRef(
        risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1",
        source_type=SourceType.GOOGLE_DRIVE,
    )


def _change(file_id: str, *, change_type: ChangeType = ChangeType.UPDATE, revision: str | None = "rev-1") -> SourceChange:
    return SourceChange(
        contract_version="1", event_id="e1", event_fingerprint="fp1",
        risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1",
        source_type=SourceType.GOOGLE_DRIVE,
        artifact=SourceArtifactRef(source_artifact_id=file_id, display_name=file_id),
        change_type=change_type, revision=revision,
        observed_at=datetime.now(timezone.utc), safe_metadata={},
    )


def test_fetch_snapshot_returns_full_text_for_tracked_file():
    async def scenario():
        drive_file = DriveFile(
            file_id="file-1", name="spec.txt", mime_type="text/plain",
            modified_time="t1", revision_id="rev-1", web_view_link="https://x",
        )
        provider = FakeDriveProvider(files={"file-1": drive_file}, texts={"file-1": "hello world"})
        adapter, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        snapshot = await adapter.fetch_snapshot(_change("file-1"))

        assert snapshot.content_scope.value == "FULL_TEXT"
        assert snapshot.text_segments[0].text == "hello world"
        assert snapshot.byte_size == len("hello world".encode("utf-8"))
        assert snapshot.resolved_revision == "rev-1"
        assert provider.export_called is True

    asyncio.run(scenario())


def test_fetch_snapshot_rejects_untracked_file():
    async def scenario():
        provider = FakeDriveProvider(files={}, texts={})
        adapter, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        with pytest.raises(PermissionDeniedError):
            await adapter.fetch_snapshot(_change("file-999"))

    asyncio.run(scenario())


def test_fetch_snapshot_delete_change_returns_unsupported_snapshot():
    async def scenario():
        provider = FakeDriveProvider(files={}, texts={})
        adapter, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        snapshot = await adapter.fetch_snapshot(_change("file-1", change_type=ChangeType.DELETE))

        assert snapshot.content_scope.value == "UNSUPPORTED"
        assert snapshot.text_segments == []
        assert snapshot.byte_size == 0

    asyncio.run(scenario())


def test_fetch_snapshot_unsupported_mime_returns_unsupported_snapshot():
    async def scenario():
        drive_file = DriveFile(
            file_id="file-1", name="image.png", mime_type="image/png",
            modified_time="t1", revision_id="rev-1", web_view_link=None,
        )
        provider = FakeDriveProvider(files={"file-1": drive_file}, texts={})
        adapter, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        snapshot = await adapter.fetch_snapshot(_change("file-1"))

        assert snapshot.content_scope.value == "UNSUPPORTED"

    asyncio.run(scenario())


def test_resolve_original_returns_provider_url():
    async def scenario():
        provider = FakeDriveProvider(files={}, texts={})
        adapter, _, _ = await _build_adapter(provider, tracked_ids=[])

        locator = await adapter.resolve_original(
            SourceArtifactRef(source_artifact_id="file-1", display_name="x")
        )

        assert locator.original_source_type.value == "PROVIDER_URL"
        assert locator.provider_url == "https://drive.google.com/file/d/file-1/view"
        assert locator.device_id is None

    asyncio.run(scenario())


def test_health_returns_healthy_when_token_valid():
    async def scenario():
        provider = FakeDriveProvider(files={}, texts={})
        adapter, _, _ = await _build_adapter(provider, tracked_ids=[])

        health = await adapter.health(_mount())

        assert health.status.value == "HEALTHY"

    asyncio.run(scenario())


def test_health_returns_offline_when_connection_not_registered():
    async def scenario():
        vault = InMemoryCredentialVault()
        lookup = InMemoryDriveConnectionLookup()
        scope_store = InMemoryRuntimeStore()
        adapter = GoogleDriveAdapter(
            provider_factory=FakeDriveProviderFactory(FakeDriveProvider(files={}, texts={})),
            credential_vault=vault,
            connection_lookup=lookup,
            tracking_scope_store=scope_store,
        )

        health = await adapter.health(_mount())

        assert health.status.value == "OFFLINE"

    asyncio.run(scenario())
