from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
    def __init__(self, changes, watch_error: Exception | None = None) -> None:
        self.changes = changes
        self.calls = []
        self.watch_calls = []
        self._watch_error = watch_error

    async def initial_changes(self, mount, selected_file_ids):
        self.calls.append((mount, selected_file_ids))
        return self.changes

    async def renew_watch(self, mount, *, address, channel_token, now):
        self.watch_calls.append((mount, address, channel_token, now))
        if self._watch_error is not None:
            raise self._watch_error
        return True


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


def test_drive_mount_registers_its_change_watch_before_the_six_hourly_job_runs():
    """붙이는 자리에서 채널을 건다.

    갱신 작업은 6 시간마다 돈다. 그것만 있으면 방금 붙인 폴더가 그때까지 밀어주는
    알림 없이 남아, 15 분 주기 대조만이 유일한 경로가 된다 (결함 39).
    """

    async def scenario() -> None:
        moment = datetime(2026, 8, 23, 11, 20, tzinfo=timezone.utc)
        adapter = _Adapter((object(),))
        publisher = DriveInitialChangePublisher(
            control_facade=_Control(),
            adapter=adapter,
            change_sink=_Sink(),
            watch_address="https://api.example/webhooks/google-drive",
            watch_channel_token="token-1",
            clock=lambda: moment,
        )

        await publisher.initialize(mount_id="mount-1", selected_file_ids=["file-1"])

        assert len(adapter.watch_calls) == 1
        mount, address, channel_token, now = adapter.watch_calls[0]
        assert mount.mount_id == "mount-1"
        assert address == "https://api.example/webhooks/google-drive"
        assert channel_token == "token-1"
        assert now == moment

    asyncio.run(scenario())


def test_drive_mount_survives_a_failed_watch_registration():
    """채널을 못 걸어도 붙은 폴더는 붙은 것이다.

    훑기는 이미 끝났고 15 분 주기 대조가 살아 있다. 여기서 던지면 알림 지연을
    피하려다 마운트 자체를 잃는다.
    """

    async def scenario() -> None:
        changes = (object(), object())
        adapter = _Adapter(changes, watch_error=RuntimeError("drive refused the channel"))
        sink = _Sink()
        publisher = DriveInitialChangePublisher(
            control_facade=_Control(),
            adapter=adapter,
            change_sink=sink,
            watch_address="https://api.example/webhooks/google-drive",
            watch_channel_token="token-1",
        )

        await publisher.initialize(mount_id="mount-1", selected_file_ids=["file-1"])

        assert sink.received == list(changes)
        assert len(adapter.watch_calls) == 1

    asyncio.run(scenario())
