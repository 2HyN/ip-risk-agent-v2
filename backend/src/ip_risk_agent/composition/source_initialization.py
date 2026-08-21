"""Initial source discovery bridges a completed mount to canonical intake."""

from __future__ import annotations


class DriveInitialChangePublisher:
    def __init__(self, *, control_facade, adapter, change_sink) -> None:
        self._control = control_facade
        self._adapter = adapter
        self._sink = change_sink

    async def initialize(
        self,
        *,
        mount_id: str,
        selected_file_ids: list[str],
    ) -> None:
        mount = await self._control.get_mount_ref(mount_id)
        changes = await self._adapter.initial_changes(mount, selected_file_ids)
        for change in changes:
            await self._sink.persist(change)


class GitHubInitialChangePublisher:
    def __init__(self, *, control_facade, adapter, change_sink) -> None:
        self._control = control_facade
        self._adapter = adapter
        self._sink = change_sink

    async def initialize(self, *, mount_id: str) -> None:
        mount = await self._control.get_mount_ref(mount_id)
        changes = await self._adapter.initial_changes(mount)
        for change in changes:
            await self._sink.persist(change)


__all__ = ["DriveInitialChangePublisher", "GitHubInitialChangePublisher"]
