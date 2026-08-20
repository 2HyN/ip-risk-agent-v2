"""channel_id -> 이 push notification이 어느 mount에 대한 건지 조회하는 포트.

Drive watch channel을 만들 때 channel_id를 우리가 발급하고, 그걸 어느
mount에 연결했는지는 Control Plane의 canonical 데이터를 알아야 한다.
GitHub의 MountResolver와 같은 성격의 Integration wiring point.
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import MountRef


class DriveChannelMountResolver(Protocol):
    async def resolve_mount(self, channel_id: str) -> MountRef | None: ...


class InMemoryDriveChannelMountResolver:
    def __init__(self) -> None:
        self._mapping: dict[str, MountRef] = {}

    def register(self, channel_id: str, mount: MountRef) -> None:
        self._mapping[channel_id] = mount

    async def resolve_mount(self, channel_id: str) -> MountRef | None:
        return self._mapping.get(channel_id)
