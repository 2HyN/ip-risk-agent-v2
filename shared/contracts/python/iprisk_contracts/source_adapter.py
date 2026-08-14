"""Behavioral boundary implemented by Source Plane adapters."""

from typing import Protocol

from .common import MountRef, OriginalSourceLocator, SourceArtifactRef, SourceHealth, SourceType, StrictModel
from .source_change import SourceChange
from .source_snapshot import SourceSnapshot


class ReconcileResult(StrictModel):
    changes: list[SourceChange]
    next_cursor: str | None = None
    has_more: bool


class SourceAdapter(Protocol):
    source_type: SourceType

    async def health(self, mount: MountRef) -> SourceHealth: ...

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot: ...

    async def resolve_original(self, artifact: SourceArtifactRef) -> OriginalSourceLocator: ...

    async def reconcile(self, mount: MountRef, cursor: str | None) -> ReconcileResult: ...

