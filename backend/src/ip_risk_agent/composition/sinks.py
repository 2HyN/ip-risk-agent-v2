"""Narrow Source-to-Control adapters."""

from __future__ import annotations

from iprisk_contracts import SourceChange


class ControlSourceChangeSink:
    def __init__(self, control_facade) -> None:
        self._control = control_facade

    async def persist(self, change: SourceChange) -> None:
        await self._control.register_source_change(change)


__all__ = ["ControlSourceChangeSink"]
