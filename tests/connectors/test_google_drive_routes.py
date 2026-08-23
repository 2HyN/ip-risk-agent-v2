from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from iprisk_contracts.common import MountRef, SourceType

from ip_risk_agent.connectors.common.change_sink import InMemorySourceChangeSink
from ip_risk_agent.connectors.common.credential_vault import CredentialScope, InMemoryCredentialVault
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.google_drive.adapter import GoogleDriveAdapter
from ip_risk_agent.connectors.google_drive.connection_lookup import (
    DriveConnectionContext,
    InMemoryDriveConnectionLookup,
)
from ip_risk_agent.connectors.google_drive.models import DriveChange, DriveChangePage
from ip_risk_agent.connectors.google_drive.mount_resolver import InMemoryDriveChannelMountResolver
from ip_risk_agent.connectors.google_drive.routes import create_drive_webhook_router
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope

CHANNEL_TOKEN = "route-channel-token"

#: 시험용 폴더. 추적 대상은 "이 폴더 안에 있는가" 로 정해진다 (§6.1 · 1-F).
FOLDER_ID = "folder-1"


class FakeDriveProvider:
    def __init__(self, changes_by_token=None, start_token="start-1", tracked=()):
        self._changes_by_token = changes_by_token or {}
        self._start_token = start_token
        self._tracked = tuple(tracked)

    def get_access_token(self):
        return ("fake-token", None)

    def get_file(self, file_id: str):
        from ip_risk_agent.connectors.google_drive.models import DriveFile

        if file_id not in self._tracked:
            raise KeyError(file_id)
        return DriveFile(
            file_id, file_id, "text/plain", "t1", "rev-1", None, (FOLDER_ID,)
        )

    def list_folder_children(self, folder_id: str, page_token: str | None = None):
        from ip_risk_agent.connectors.google_drive.models import DriveFolderPage

        return DriveFolderPage(
            files=tuple(self.get_file(item) for item in self._tracked),
            next_page_token=None,
        )

    def get_start_page_token(self) -> str:
        return self._start_token

    def create_google_doc(self, name: str):
        raise NotImplementedError

    def list_changes(self, page_token: str) -> DriveChangePage:
        return self._changes_by_token[page_token]

    def read_text(self, file_id: str, mime_type: str) -> str:
        raise NotImplementedError

    def export_token(self) -> dict:
        return {"access_token": "refreshed", "refresh_token": "rt", "expires_at": None, "scope": "x"}


class FakeDriveProviderFactory:
    def __init__(self, provider: FakeDriveProvider) -> None:
        self._provider = provider

    def create(self) -> FakeDriveProvider:
        return self._provider


def _mount() -> MountRef:
    return MountRef(risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1", source_type=SourceType.GOOGLE_DRIVE)


async def _build_client(provider: FakeDriveProvider, *, tracked_ids=None, register_channel: bool = True):
    vault = InMemoryCredentialVault()
    lookup = InMemoryDriveConnectionLookup()
    scope_store = InMemoryRuntimeStore()
    runtime_store = InMemoryRuntimeStore()

    cred_scope = CredentialScope(provider=SourceType.GOOGLE_DRIVE, connection_id="conn-1", secret_name="tok")
    token_json = json.dumps({"access_token": "at", "refresh_token": "rt", "expires_at": None, "scope": "x"})
    ref = await vault.put(cred_scope, token_json)
    lookup.register("mount-1", DriveConnectionContext(connection_id="conn-1", credential_ref=ref))
    await scope_store.save(
        "mount-1",
        DriveTrackingScope(mount_id="mount-1", folder_id=FOLDER_ID, display_metadata_by_file={}),
    )

    provider._tracked = tuple(tracked_ids or [])

    adapter = GoogleDriveAdapter(
        provider_factory=FakeDriveProviderFactory(provider),
        connection_lookup=lookup,
        tracking_scope_store=scope_store,
        runtime_store=runtime_store,
    )

    channel_resolver = InMemoryDriveChannelMountResolver()
    if register_channel:
        channel_resolver.register("channel-1", _mount())
    sink = InMemorySourceChangeSink()

    router = create_drive_webhook_router(
        adapter=adapter, channel_resolver=channel_resolver, channel_token=CHANNEL_TOKEN, change_sink=sink
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, sink


def test_sync_message_is_acked_without_reconcile():
    async def scenario():
        provider = FakeDriveProvider()
        client, sink = await _build_client(provider)

        response = client.post(
            "/webhooks/google-drive",
            headers={
                "X-Goog-Channel-Token": CHANNEL_TOKEN,
                "X-Goog-Resource-State": "sync",
                "X-Goog-Channel-ID": "channel-1",
            },
        )

        assert response.status_code == 200
        assert response.json()["reason"] == "sync_ack"
        assert sink.received == []

    asyncio.run(scenario())


def test_change_notification_triggers_reconcile_and_persists_changes():
    async def scenario():
        page = DriveChangePage(
            changes=[DriveChange(file_id="file-1", removed=False, modified_time="t1", revision_id="r1")],
            next_page_token=None,
            new_start_page_token="c2",
        )
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        client, sink = await _build_client(provider, tracked_ids=["file-1"])

        response = client.post(
            "/webhooks/google-drive",
            headers={
                "X-Goog-Channel-Token": CHANNEL_TOKEN,
                "X-Goog-Resource-State": "change",
                "X-Goog-Channel-ID": "channel-1",
            },
        )

        assert response.status_code == 200
        assert response.json()["changes_persisted"] == 1
        assert len(sink.received) == 1
        assert sink.received[0].artifact.source_artifact_id == "file-1"

    asyncio.run(scenario())


def test_invalid_channel_token_returns_401():
    async def scenario():
        provider = FakeDriveProvider()
        client, sink = await _build_client(provider)

        response = client.post(
            "/webhooks/google-drive",
            headers={
                "X-Goog-Channel-Token": "wrong-token",
                "X-Goog-Resource-State": "change",
                "X-Goog-Channel-ID": "channel-1",
            },
        )

        assert response.status_code == 401
        assert sink.received == []

    asyncio.run(scenario())


def test_unknown_channel_returns_ok_with_no_changes():
    async def scenario():
        provider = FakeDriveProvider()
        client, sink = await _build_client(provider, register_channel=False)

        response = client.post(
            "/webhooks/google-drive",
            headers={
                "X-Goog-Channel-Token": CHANNEL_TOKEN,
                "X-Goog-Resource-State": "change",
                "X-Goog-Channel-ID": "channel-unknown",
            },
        )

        assert response.status_code == 200
        assert response.json()["reason"] == "unknown_channel"
        assert sink.received == []

    asyncio.run(scenario())


def test_paginated_reconcile_persists_all_pages():
    async def scenario():
        page1 = DriveChangePage(
            changes=[DriveChange(file_id="file-1", removed=False, modified_time="t1", revision_id="r1")],
            next_page_token="page-2",
            new_start_page_token=None,
        )
        page2 = DriveChangePage(
            changes=[DriveChange(file_id="file-2", removed=False, modified_time="t2", revision_id="r2")],
            next_page_token=None,
            new_start_page_token="final-cursor",
        )
        provider = FakeDriveProvider(changes_by_token={"start-1": page1, "page-2": page2})
        client, sink = await _build_client(provider, tracked_ids=["file-1", "file-2"])

        response = client.post(
            "/webhooks/google-drive",
            headers={
                "X-Goog-Channel-Token": CHANNEL_TOKEN,
                "X-Goog-Resource-State": "change",
                "X-Goog-Channel-ID": "channel-1",
            },
        )

        assert response.status_code == 200
        assert response.json()["changes_persisted"] == 2
        assert len(sink.received) == 2

    asyncio.run(scenario())
