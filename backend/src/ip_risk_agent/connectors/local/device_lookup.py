"""mount_id -> device_id 조회 포트. Drive의 connection_lookup.py와 동일 패턴."""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import StrictModel

from ..common.errors import NotFoundError


class LocalDeviceContext(StrictModel):
    device_id: str
    mount_handle: str


class LocalDeviceLookup(Protocol):
    async def resolve(self, mount_id: str) -> LocalDeviceContext: ...


class InMemoryLocalDeviceLookup:
    def __init__(self) -> None:
        self._mapping: dict[str, LocalDeviceContext] = {}

    def register(self, mount_id: str, context: LocalDeviceContext) -> None:
        self._mapping[mount_id] = context

    async def resolve(self, mount_id: str) -> LocalDeviceContext:
        try:
            return self._mapping[mount_id]
        except KeyError as exc:
            raise NotFoundError(
                provider="local", safe_message=f"no device registered for mount {mount_id}"
            ) from exc
