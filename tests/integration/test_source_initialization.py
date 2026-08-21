from __future__ import annotations

import asyncio

from iprisk_contracts import MountRef, SourceType

from ip_risk_agent.composition.source_initialization import (
    DriveInitialChangePublisher,
    GitHubInitialChangePublisher,
)


class _Control:
    async def get_mount_ref(self, mount_id: str) -> MountRef:
        assert mount_id == "mount-1"
        return MountRef(
            risk_workspace_id="vws-1",
            mount_id=mount_id,
            source_workspace_id="source-1",
            source_type=SourceType.GOOGLE_DRIVE,
        )


class _Adapter:
    def __init__(self, changes) -> None:
        self.changes = changes
        self.calls = []

    async def initial_changes(self, mount, selected_file_ids):
        self.calls.append((mount, selected_file_ids))
        return self.changes


class _GitHubAdapter:
    def __init__(self, changes) -> None:
        self.changes = changes
        self.mounts = []

    async def initial_changes(self, mount):
        self.mounts.append(mount)
        return self.changes


class _Sink:
    def __init__(self) -> None:
        self.received = []

    async def persist(self, change) -> None:
        self.received.append(change)


def test_drive_mount_initialization_publishes_every_selected_change_to_intake_sink():
    async def scenario() -> None:
        changes = (object(), object())
        adapter = _Adapter(changes)
        sink = _Sink()
        publisher = DriveInitialChangePublisher(
            control_facade=_Control(),
            adapter=adapter,
            change_sink=sink,
        )

        await publisher.initialize(
            mount_id="mount-1",
            selected_file_ids=["file-1", "file-2"],
        )

        mount, selected = adapter.calls[0]
        assert mount.risk_workspace_id == "vws-1"
        assert selected == ["file-1", "file-2"]
        assert sink.received == list(changes)

    asyncio.run(scenario())


def test_github_mount_initialization_publishes_repository_tree_changes():
    async def scenario() -> None:
        changes = (object(), object())
        adapter = _GitHubAdapter(changes)
        sink = _Sink()
        publisher = GitHubInitialChangePublisher(
            control_facade=_Control(),
            adapter=adapter,
            change_sink=sink,
        )

        await publisher.initialize(mount_id="mount-1")

        assert adapter.mounts[0].risk_workspace_id == "vws-1"
        assert sink.received == list(changes)

    asyncio.run(scenario())
