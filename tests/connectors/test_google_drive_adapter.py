from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts.common import ChangeType, MountRef, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange

from ip_risk_agent.connectors.common.credential_vault import (
    CredentialScope,
    InMemoryCredentialVault,
)
from ip_risk_agent.connectors.common.errors import PermissionDeniedError
from ip_risk_agent.connectors.common.runtime_store import DriveRuntime, InMemoryRuntimeStore
from ip_risk_agent.connectors.google_drive.adapter import GoogleDriveAdapter
from ip_risk_agent.connectors.google_drive.connection_lookup import (
    DriveConnectionContext,
    InMemoryDriveConnectionLookup,
)
from ip_risk_agent.connectors.google_drive.models import (
    DriveChange,
    DriveChangePage,
    DriveFile,
    DriveWatchChannel,
)
from ip_risk_agent.connectors.google_drive.models import (
    FOLDER_MIME_TYPE,
)
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope

#: 시험용 폴더. 추적 대상은 "이 폴더 안에 있는가" 로 정해진다 (§6.1 · 1-F).
FOLDER_ID = "folder-1"


class FakeDriveProvider:
    def __init__(self, files=None, texts=None, changes_by_token=None, start_token="start-1"):
        self._files = files or {}
        self._texts = texts or {}
        self._changes_by_token = changes_by_token or {}
        self._start_token = start_token
        self.export_called = False
        self.get_start_page_token_called = False
        self.watch_requests = []

    def get_access_token(self):
        return ("fake-token", None)

    def get_file(self, file_id: str) -> DriveFile:
        if file_id == FOLDER_ID:
            return DriveFile(FOLDER_ID, "tracked", FOLDER_MIME_TYPE, None, None, None, ())
        return self._files[file_id]

    def list_folder_children(self, folder_id: str, page_token: str | None = None):
        from ip_risk_agent.connectors.google_drive.models import DriveFolderPage

        return DriveFolderPage(
            files=tuple(
                item for item in self._files.values() if folder_id in item.parents
            ),
            next_page_token=None,
        )

    def get_start_page_token(self) -> str:
        self.get_start_page_token_called = True
        return self._start_token

    def create_google_doc(self, name: str):
        raise NotImplementedError

    def list_changes(self, page_token: str) -> DriveChangePage:
        return self._changes_by_token[page_token]

    def watch_changes(self, **request) -> DriveWatchChannel:
        self.watch_requests.append(request)
        return DriveWatchChannel(
            channel_id=request["channel_id"],
            resource_id="resource-1",
            expiration_millis=request["expiration_millis"],
        )

    def read_text(self, file_id: str, mime_type: str) -> str:
        return self._texts[file_id]

    def export_token(self) -> dict:
        self.export_called = True
        return {"access_token": "refreshed", "refresh_token": "rt", "expires_at": None, "scope": "x"}


class FakeDriveProviderFactory:
    def __init__(self, provider: FakeDriveProvider) -> None:
        self._provider = provider

    def create(self) -> FakeDriveProvider:
        return self._provider


async def _build_adapter(
    provider: FakeDriveProvider,
    *,
    tracked_ids: list[str],
    display_metadata_by_file: dict | None = None,
    runtime_store: InMemoryRuntimeStore | None = None,
):
    vault = InMemoryCredentialVault()
    lookup = InMemoryDriveConnectionLookup()
    scope_store = InMemoryRuntimeStore()
    runtime_store = runtime_store if runtime_store is not None else InMemoryRuntimeStore()

    cred_scope = CredentialScope(provider=SourceType.GOOGLE_DRIVE, connection_id="conn-1", secret_name="tok")
    token_json = json.dumps({"access_token": "at", "refresh_token": "rt", "expires_at": None, "scope": "x"})
    ref = await vault.put(cred_scope, token_json)
    lookup.register("mount-1", DriveConnectionContext(connection_id="conn-1", credential_ref=ref))

    # `tracked_ids` 는 이제 **폴더 안에 넣을 파일**이다. 명단이 아니라 소속으로
    # 판정하므로, 대역의 파일에 부모를 붙여 준다.
    for file_id in tracked_ids:
        found = provider._files.get(file_id)
        if found is None:
            # 시험이 내용을 신경 쓰지 않는 경우. "폴더 안에 있다" 만 세운다.
            provider._files[file_id] = DriveFile(
                file_id, file_id, "text/plain", "t1", "rev-1", None, (FOLDER_ID,)
            )
        elif not found.parents:
            provider._files[file_id] = replace(found, parents=(FOLDER_ID,))

    await scope_store.save(
        "mount-1",
        DriveTrackingScope(
            mount_id="mount-1",
            folder_id=FOLDER_ID,
            display_metadata_by_file=display_metadata_by_file or {},
        ),
    )

    adapter = GoogleDriveAdapter(
        provider_factory=FakeDriveProviderFactory(provider),
        connection_lookup=lookup,
        tracking_scope_store=scope_store,
        runtime_store=runtime_store,
    )
    return adapter, vault, ref, runtime_store


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
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        snapshot = await adapter.fetch_snapshot(_change("file-1"))

        assert snapshot.content_scope.value == "FULL_TEXT"
        assert snapshot.text_segments[0].text == "hello world"
        # D1 — 보관할 자격증명이 없다. 토큰을 되쓰는 순간 이 결정이 없애려던
        # 그 보관물이 되살아난다.
        assert provider.export_called is False

    asyncio.run(scenario())


def test_fetch_snapshot_rejects_untracked_file():
    async def scenario():
        provider = FakeDriveProvider()
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        with pytest.raises(PermissionDeniedError):
            await adapter.fetch_snapshot(_change("file-999"))

    asyncio.run(scenario())


def test_fetch_snapshot_delete_change_returns_unsupported_snapshot():
    async def scenario():
        provider = FakeDriveProvider()
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        snapshot = await adapter.fetch_snapshot(_change("file-1", change_type=ChangeType.DELETE))

        assert snapshot.content_scope.value == "UNSUPPORTED"

    asyncio.run(scenario())


def test_fetch_snapshot_unsupported_mime_returns_unsupported_snapshot():
    async def scenario():
        drive_file = DriveFile(
            file_id="file-1", name="image.png", mime_type="image/png",
            modified_time="t1", revision_id="rev-1", web_view_link=None,
        )
        provider = FakeDriveProvider(files={"file-1": drive_file})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        snapshot = await adapter.fetch_snapshot(_change("file-1"))

        assert snapshot.content_scope.value == "UNSUPPORTED"

    asyncio.run(scenario())


def test_resolve_original_returns_provider_url():
    async def scenario():
        provider = FakeDriveProvider()
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[])

        locator = await adapter.resolve_original(
            SourceArtifactRef(source_artifact_id="file-1", display_name="x")
        )

        assert locator.original_source_type.value == "PROVIDER_URL"
        assert locator.provider_url == "https://drive.google.com/file/d/file-1/view"

    asyncio.run(scenario())


def test_health_returns_healthy_when_token_valid():
    async def scenario():
        provider = FakeDriveProvider()
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[])

        health = await adapter.health(_mount())

        assert health.status.value == "HEALTHY"

    asyncio.run(scenario())


def test_health_returns_offline_when_connection_not_registered():
    async def scenario():
        vault = InMemoryCredentialVault()
        lookup = InMemoryDriveConnectionLookup()
        scope_store = InMemoryRuntimeStore()
        runtime_store = InMemoryRuntimeStore()
        adapter = GoogleDriveAdapter(
            provider_factory=FakeDriveProviderFactory(FakeDriveProvider()),
            connection_lookup=lookup,
            tracking_scope_store=scope_store,
            runtime_store=runtime_store,
        )

        health = await adapter.health(_mount())

        assert health.status.value == "OFFLINE"

    asyncio.run(scenario())


def test_reconcile_filters_out_untracked_files():
    async def scenario():
        page = DriveChangePage(
            changes=[
                DriveChange(file_id="file-1", removed=False, modified_time="t1", revision_id="r1"),
                DriveChange(file_id="file-2", removed=False, modified_time="t2", revision_id="r2"),
            ],
            next_page_token=None,
            new_start_page_token="cursor-2",
        )
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        result = await adapter.reconcile(_mount(), cursor=None)

        assert len(result.changes) == 1
        assert result.changes[0].artifact.source_artifact_id == "file-1"

    asyncio.run(scenario())


def test_reconcile_bootstraps_cursor_when_none_persisted():
    async def scenario():
        page = DriveChangePage(changes=[], next_page_token=None, new_start_page_token="c2")
        provider = FakeDriveProvider(changes_by_token={"start-1": page}, start_token="start-1")
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[])

        await adapter.reconcile(_mount(), cursor=None)

        assert provider.get_start_page_token_called is True

    asyncio.run(scenario())


def test_reconcile_uses_persisted_cursor_over_bootstrap():
    async def scenario():
        runtime_store = InMemoryRuntimeStore()
        await runtime_store.save("conn-1", DriveRuntime(connection_id="conn-1", change_cursor="persisted-cursor"))
        page = DriveChangePage(changes=[], next_page_token=None, new_start_page_token="c-next")
        provider = FakeDriveProvider(changes_by_token={"persisted-cursor": page})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[], runtime_store=runtime_store)

        result = await adapter.reconcile(_mount(), cursor=None)

        assert provider.get_start_page_token_called is False
        assert result.next_cursor == "c-next"

    asyncio.run(scenario())


def test_reconcile_explicit_cursor_overrides_persisted():
    async def scenario():
        runtime_store = InMemoryRuntimeStore()
        await runtime_store.save("conn-1", DriveRuntime(connection_id="conn-1", change_cursor="persisted-cursor"))
        page = DriveChangePage(changes=[], next_page_token=None, new_start_page_token="c-explicit")
        provider = FakeDriveProvider(changes_by_token={"explicit-cursor": page})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[], runtime_store=runtime_store)

        result = await adapter.reconcile(_mount(), cursor="explicit-cursor")

        assert result.next_cursor == "c-explicit"

    asyncio.run(scenario())


def test_reconcile_persists_cursor_when_final_page():
    async def scenario():
        page = DriveChangePage(changes=[], next_page_token=None, new_start_page_token="final-cursor")
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        adapter, _, _, runtime_store = await _build_adapter(provider, tracked_ids=[])

        await adapter.reconcile(_mount(), cursor=None)

        saved = await runtime_store.load("conn-1")
        assert saved is not None
        assert saved.change_cursor == "final-cursor"

    asyncio.run(scenario())


def test_initial_changes_publish_only_picker_scoped_files_with_provider_revisions():
    async def scenario():
        files = {
            "file-1": DriveFile(
                file_id="file-1", name="Claims.txt", mime_type="text/plain",
                modified_time="t1", revision_id="rev-1", web_view_link=None,
            ),
            "file-2": DriveFile(
                file_id="file-2", name="Prior art.pdf", mime_type="application/pdf",
                modified_time="t2", revision_id="rev-2", web_view_link=None,
            ),
        }
        provider = FakeDriveProvider(files=files)
        adapter, _, _, _ = await _build_adapter(
            provider,
            tracked_ids=["file-1", "file-2"],
        )

        changes = await adapter.initial_changes(_mount(), ["file-1", "file-2"])

        assert [change.artifact.source_artifact_id for change in changes] == [
            "file-1",
            "file-2",
        ]
        assert [change.artifact.display_name for change in changes] == [
            "Claims.txt",
            "Prior art.pdf",
        ]
        assert [change.revision for change in changes] == ["rev-1", "rev-2"]
        assert all(change.change_type is ChangeType.CREATE for change in changes)
        # D1 — 보관할 자격증명이 없다. 토큰을 되쓰는 순간 이 결정이 없애려던
        # 그 보관물이 되살아난다.
        assert provider.export_called is False

    asyncio.run(scenario())


def test_initial_changes_walk_the_folder_not_a_given_list():
    """처음 훑기는 **폴더가 정한다.** 부르는 쪽이 목록을 주지 않는다 (§6.1 · 1-F).

    예전에는 Picker 가 고른 목록을 받아 그것만 훑었다. 그래서 마운트 시점에 폴더에
    이미 있던 파일이라도 목록에 없으면 발견되지 않았고, 그 뒤에 넣은 파일도
    마찬가지였다.
    """

    async def scenario():
        inside = DriveFile(
            file_id="file-1", name="a.md", mime_type="text/markdown",
            modified_time="t1", revision_id="rev-1", web_view_link=None,
            parents=(FOLDER_ID,),
        )
        outside = DriveFile(
            file_id="file-2", name="b.md", mime_type="text/markdown",
            modified_time="t2", revision_id="rev-2", web_view_link=None,
            parents=("somewhere-else",),
        )
        provider = FakeDriveProvider(files={"file-1": inside, "file-2": outside})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[])

        changes = await adapter.initial_changes(_mount())

        found = {change.artifact.source_artifact_id for change in changes}
        assert found == {"file-1"}, "폴더 밖은 훑지 않는다"

    asyncio.run(scenario())


def test_a_file_added_after_the_mount_is_picked_up():
    """이것이 폴더로 바꾼 이유다.

    예전 명단 방식에서는 변경 피드에 와도 명단에 없다고 버려졌다. v1 이 그렇게
    실패했고 — 폴더 펼침이 **연결 시점의 스냅샷**이었다 — 이 서비스를 쓰는 방법이
    바로 그 "폴더에 넣는 것" 이다.
    """

    async def scenario():
        added = DriveFile(
            file_id="file-new", name="c.md", mime_type="text/markdown",
            modified_time="t3", revision_id="rev-3", web_view_link=None,
            parents=(FOLDER_ID,),
        )
        page = DriveChangePage(
            changes=[
                DriveChange(file_id="file-new", removed=False, modified_time="t3", revision_id="rev-3")
            ],
            next_page_token=None,
            new_start_page_token="cursor-2",
        )
        provider = FakeDriveProvider(
            files={"file-new": added}, changes_by_token={"start-1": page}
        )
        # 마운트할 때는 이 파일이 없었다 — 명단에 있을 수가 없다.
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[])

        result = await adapter.reconcile(_mount(), cursor=None)

        assert [c.artifact.source_artifact_id for c in result.changes] == ["file-new"]

    asyncio.run(scenario())


def test_a_shortcut_inside_the_folder_is_not_followed():
    """바로가기를 따라가면 **폴더 밖의 파일이 읽힌다** (§6.1).

    지금까지는 통과 목록에 없어서 막혔는데 그것은 규칙이 아니라 우연이었다.
    """
    from ip_risk_agent.connectors.google_drive.models import SHORTCUT_MIME_TYPE

    async def scenario():
        shortcut = DriveFile(
            file_id="link-1", name="notes.md", mime_type=SHORTCUT_MIME_TYPE,
            modified_time="t1", revision_id="rev-1", web_view_link=None,
            parents=(FOLDER_ID,),
        )
        provider = FakeDriveProvider(files={"link-1": shortcut})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=[])

        assert await adapter.initial_changes(_mount()) == ()

    asyncio.run(scenario())


def test_watch_renewal_persists_channel_and_reconcile_preserves_it():
    async def scenario():
        now = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
        page = DriveChangePage(
            changes=[],
            next_page_token=None,
            new_start_page_token="cursor-after-reconcile",
        )
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        adapter, _, _, runtime_store = await _build_adapter(
            provider,
            tracked_ids=[],
        )

        assert await adapter.renew_watch(
            _mount(),
            address="https://api.example.com/webhooks/google-drive",
            channel_token="opaque-channel-token",
            now=now,
        )
        watched = await runtime_store.load("conn-1")
        assert watched is not None
        assert watched.watch_resource_id == "resource-1"
        assert watched.watch_expiry == now + timedelta(days=6)
        assert provider.watch_requests[0]["page_token"] == "start-1"

        await adapter.reconcile(_mount(), cursor=None)
        reconciled = await runtime_store.load("conn-1")
        assert reconciled is not None
        assert reconciled.change_cursor == "cursor-after-reconcile"
        assert reconciled.watch_resource_id == "resource-1"

        assert not await adapter.renew_watch(
            _mount(),
            address="https://api.example.com/webhooks/google-drive",
            channel_token="opaque-channel-token",
            now=now + timedelta(hours=1),
        )
        assert len(provider.watch_requests) == 1

    asyncio.run(scenario())


def test_reconcile_does_not_persist_cursor_when_more_pages_remain():
    async def scenario():
        page = DriveChangePage(changes=[], next_page_token="page-2", new_start_page_token=None)
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        adapter, _, _, runtime_store = await _build_adapter(provider, tracked_ids=[])

        result = await adapter.reconcile(_mount(), cursor=None)

        assert result.has_more is True
        assert result.next_cursor == "page-2"
        assert await runtime_store.load("conn-1") is None

    asyncio.run(scenario())


def test_reconcile_marks_removed_file_as_delete():
    async def scenario():
        page = DriveChangePage(
            changes=[DriveChange(file_id="file-1", removed=True, modified_time=None, revision_id=None)],
            next_page_token=None,
            new_start_page_token="c2",
        )
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        adapter, _, _, _ = await _build_adapter(provider, tracked_ids=["file-1"])

        result = await adapter.reconcile(_mount(), cursor=None)

        assert result.changes[0].change_type.value == "DELETE"

    asyncio.run(scenario())


def test_reconcile_uses_display_metadata_name_when_available():
    async def scenario():
        page = DriveChangePage(
            changes=[DriveChange(file_id="file-1", removed=False, modified_time="t1", revision_id="r1")],
            next_page_token=None,
            new_start_page_token="c2",
        )
        provider = FakeDriveProvider(changes_by_token={"start-1": page})
        adapter, _, _, _ = await _build_adapter(
            provider,
            tracked_ids=["file-1"],
            display_metadata_by_file={"file-1": {"name": "My Spec Doc"}},
        )

        result = await adapter.reconcile(_mount(), cursor=None)

        assert result.changes[0].artifact.display_name == "My Spec Doc"

    asyncio.run(scenario())


def test_initial_changes_captures_the_change_cursor_at_mount_time():
    """mount 시점에 커서를 잡지 않으면 그때부터 첫 reconcile 까지가 사각지대가 된다.

    reconcile 은 커서가 없으면 `getStartPageToken()` 즉 "지금부터" 로 시작하므로,
    커서를 첫 실행 때 잡으면 mount 직후의 파일 수정이 초기 스냅샷에도 이후
    reconcile 에도 잡히지 않고 영구히 사라진다. 운영에서 실제로 그렇게 사라졌다.
    """

    async def scenario():
        files = {
            "file-1": DriveFile(
                file_id="file-1",
                name="requirements.txt",
                mime_type="text/plain",
                modified_time="2026-08-21T10:00:00Z",
                revision_id="3",
                web_view_link=None,
            )
        }
        provider = FakeDriveProvider(files=files)
        adapter, _, _, runtime_store = await _build_adapter(
            provider, tracked_ids=["file-1"]
        )

        await adapter.initial_changes(_mount(), ["file-1"])

        runtime = await runtime_store.load("conn-1")
        assert runtime is not None
        assert runtime.change_cursor == provider._start_token

    asyncio.run(scenario())


def test_initial_changes_does_not_rewind_an_existing_cursor():
    """이미 진행된 커서를 mount 가 되감으면 처리한 변경을 다시 흘린다."""

    async def scenario():
        files = {
            "file-1": DriveFile(
                file_id="file-1",
                name="requirements.txt",
                mime_type="text/plain",
                modified_time="2026-08-21T10:00:00Z",
                revision_id="3",
                web_view_link=None,
            )
        }
        provider = FakeDriveProvider(files=files)
        runtime_store = InMemoryRuntimeStore()
        await runtime_store.save(
            "conn-1", DriveRuntime(connection_id="conn-1", change_cursor="already-advanced")
        )
        adapter, _, _, _ = await _build_adapter(
            provider, tracked_ids=["file-1"], runtime_store=runtime_store
        )

        await adapter.initial_changes(_mount(), ["file-1"])

        runtime = await runtime_store.load("conn-1")
        assert runtime.change_cursor == "already-advanced"

    asyncio.run(scenario())
