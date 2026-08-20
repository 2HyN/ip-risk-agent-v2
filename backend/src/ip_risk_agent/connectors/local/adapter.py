"""Master Spec 9번 SourceAdapter 계약의 Local 구현."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import PurePosixPath

from iprisk_contracts.common import (
    ArtifactKind,
    ChangeType,
    ContentScope,
    MountRef,
    OriginalSourceLocator,
    OriginalSourceType,
    SegmentKind,
    SourceAccessType,
    SourceArtifactRef,
    SourceHealth,
    SourceHealthStatus,
    SourceType,
    TextSegment,
)
from iprisk_contracts.source_adapter import ReconcileResult
from iprisk_contracts.source_change import SourceChange
from iprisk_contracts.source_snapshot import SourceSnapshot

from ..common.adapter_support import build_access_receipt, bytes_of_text
from ..common.errors import NotFoundError, SourceConnectorError, UnsupportedContentError
from ..common.runtime_store import LocalConnectionStatus, LocalRuntime
from .device_lookup import LocalDeviceLookup
from .identity import decode_local_artifact_id
from .staging_store import LocalStagingStore, StagingRef

_MANIFEST_NAMES = {"requirements.txt", "package.json", "pyproject.toml", "setup.py", "setup.cfg"}
_CODE_EXTENSIONS = {".py", ".js", ".ts", ".java", ".go", ".c", ".h", ".cpp", ".rs"}
_DOC_EXTENSIONS = {".md", ".txt", ".rst"}


class LocalAdapter:
    source_type = SourceType.LOCAL

    def __init__(
        self,
        *,
        staging_store: LocalStagingStore,
        device_lookup: LocalDeviceLookup,
        runtime_store,
    ) -> None:
        self._staging_store = staging_store
        self._device_lookup = device_lookup
        self._runtime_store = runtime_store

    async def health(self, mount: MountRef) -> SourceHealth:
        try:
            device = await self._device_lookup.resolve(mount.mount_id)
        except NotFoundError:
            return SourceHealth(
                status=SourceHealthStatus.OFFLINE,
                checked_at=datetime.now(timezone.utc),
                safe_metadata={},
            )

        runtime: LocalRuntime | None = await self._runtime_store.load(device.device_id)
        if runtime is None or runtime.status is not LocalConnectionStatus.ONLINE:
            status = SourceHealthStatus.OFFLINE
        else:
            status = SourceHealthStatus.HEALTHY

        return SourceHealth(status=status, checked_at=datetime.now(timezone.utc), safe_metadata={})

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot:
        if change.change_type is ChangeType.DELETE:
            return self._unsupported_snapshot(change, resolved_revision=change.revision or "deleted")

        staging_object_name = change.safe_metadata.get("staging_object_name")
        if not isinstance(staging_object_name, str) or not staging_object_name:
            raise UnsupportedContentError(
                provider="local",
                safe_message="local change is missing a staging reference",
            )

        ref = StagingRef(object_name=staging_object_name)
        text = await self._staging_store.get(ref)

        segment = TextSegment(segment_id="full", text=text, segment_kind=SegmentKind.FULL)
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        receipt = build_access_receipt(
            SourceAccessType.FULL_CONTENT, content_bytes=bytes_of_text(text)
        )

        snapshot = SourceSnapshot(
            contract_version="1",
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=SourceType.LOCAL,
            source_artifact_id=change.artifact.source_artifact_id,
            resolved_revision=change.revision or checksum[:16],
            retrieved_at=datetime.now(timezone.utc),
            display_name=change.artifact.display_name,
            logical_path_hint=change.artifact.path_hint,
            mime_type=None,
            artifact_kind=self._infer_artifact_kind(change.artifact.display_name),
            content_scope=ContentScope.FULL_TEXT,
            text_segments=[segment],
            checksum=checksum,
            byte_size=bytes_of_text(text),
            source_access_receipt=receipt,
        )

        try:
            await self._staging_store.delete(ref)
        except SourceConnectorError:
            pass  # best-effort; TTL이 진짜 안전망이다 (Agent2 Spec 30/32번)

        return snapshot

    def _unsupported_snapshot(self, change: SourceChange, *, resolved_revision: str) -> SourceSnapshot:
        receipt = build_access_receipt(SourceAccessType.METADATA, content_bytes=0)
        return SourceSnapshot(
            contract_version="1",
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=SourceType.LOCAL,
            source_artifact_id=change.artifact.source_artifact_id,
            resolved_revision=resolved_revision,
            retrieved_at=datetime.now(timezone.utc),
            display_name=change.artifact.display_name,
            logical_path_hint=change.artifact.path_hint,
            mime_type=None,
            artifact_kind=ArtifactKind.UNKNOWN,
            content_scope=ContentScope.UNSUPPORTED,
            text_segments=[],
            checksum=hashlib.sha256(resolved_revision.encode("utf-8")).hexdigest(),
            byte_size=0,
            source_access_receipt=receipt,
        )

    @staticmethod
    def _infer_artifact_kind(display_name: str) -> ArtifactKind:
        lowered = display_name.lower()
        if lowered in _MANIFEST_NAMES:
            return ArtifactKind.MANIFEST
        if lowered.endswith(".lock") or lowered.endswith("lockfile"):
            return ArtifactKind.LOCKFILE
        suffix = PurePosixPath(lowered).suffix
        if suffix in _CODE_EXTENSIONS:
            return ArtifactKind.SOURCE_CODE
        if suffix in _DOC_EXTENSIONS:
            return ArtifactKind.DOCUMENT_TEXT
        return ArtifactKind.UNKNOWN

    async def resolve_original(self, artifact: SourceArtifactRef) -> OriginalSourceLocator:
        try:
            identity = decode_local_artifact_id(artifact.source_artifact_id)
        except ValueError as exc:
            raise UnsupportedContentError(
                provider="local", safe_message="malformed local artifact id"
            ) from exc

        return OriginalSourceLocator(
            original_source_type=OriginalSourceType.LOCAL_DEVICE,
            device_id=identity.device_id,
            source_artifact_id=artifact.source_artifact_id,
            metadata_safe={},
        )

    async def reconcile(self, mount: MountRef, cursor: str | None) -> ReconcileResult:
        # Agent 2 Spec 43번: Local은 Desktop이 offline이면 cloud reconcile 자체가
        # 불가능하다. push(watcher event)가 주 경로이므로 안전한 no-op만 제공한다.
        return ReconcileResult(changes=[], next_cursor=cursor, has_more=False)
