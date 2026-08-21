"""Master Spec 9번 SourceAdapter 계약의 Drive 구현.

models.py의 DriveProvider Protocol에만 의존한다 (client.py를 직접
import하지 않음) — 그래서 googleapiclient 설치 여부와 무관하게 지금
바로 테스트할 수 있다. 운영 시엔 client.GoogleDriveProviderFactory가,
테스트에선 Fake factory가 provider_factory로 주입된다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

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
from ..common.credential_vault import SourceCredentialVault
from ..common.errors import (
    AuthRequiredError,
    NotFoundError,
    PermissionDeniedError,
    SourceConnectorError,
)
from ..common.fingerprint import drive_change_fingerprint
from ..common.runtime_store import DriveRuntime
from .connection_lookup import DriveConnectionContext, DriveConnectionLookup
from .models import SELECTABLE_MIME_TYPES, DriveProvider
from .tracking_scope import DriveTrackingScope


class DriveProviderFactory(Protocol):
    def create(self, token: dict) -> DriveProvider: ...


class GoogleDriveAdapter:
    source_type = SourceType.GOOGLE_DRIVE

    def __init__(
        self,
        *,
        provider_factory: DriveProviderFactory,
        credential_vault: SourceCredentialVault,
        connection_lookup: DriveConnectionLookup,
        tracking_scope_store,
        runtime_store,
    ) -> None:
        self._provider_factory = provider_factory
        self._credential_vault = credential_vault
        self._connection_lookup = connection_lookup
        self._tracking_scope_store = tracking_scope_store
        self._runtime_store = runtime_store

    async def _provider_for_mount(
        self, mount_id: str
    ) -> tuple[DriveProvider, DriveConnectionContext]:
        connection = await self._connection_lookup.resolve(mount_id)
        raw_token = await self._credential_vault.get(connection.credential_ref)
        token = json.loads(raw_token)
        provider = self._provider_factory.create(token)
        return provider, connection

    async def _persist_refreshed_token(
        self, connection: DriveConnectionContext, provider: DriveProvider
    ) -> None:
        await self._credential_vault.update(
            connection.credential_ref, json.dumps(provider.export_token())
        )

    async def health(self, mount: MountRef) -> SourceHealth:
        try:
            provider, connection = await self._provider_for_mount(mount.mount_id)
            provider.get_access_token()
            await self._persist_refreshed_token(connection, provider)
            status = SourceHealthStatus.HEALTHY
        except AuthRequiredError:
            status = SourceHealthStatus.REAUTH_REQUIRED
        except PermissionDeniedError:
            status = SourceHealthStatus.PERMISSION_DENIED
        except NotFoundError:
            status = SourceHealthStatus.OFFLINE
        except SourceConnectorError:
            status = SourceHealthStatus.DEGRADED
        return SourceHealth(status=status, checked_at=datetime.now(timezone.utc), safe_metadata={})

    async def renew_watch(
        self,
        mount: MountRef,
        *,
        address: str,
        channel_token: str,
        now: datetime,
        renewal_window: timedelta = timedelta(hours=24),
        lifetime: timedelta = timedelta(days=6),
    ) -> bool:
        """Replace an absent/expiring Drive changes channel.

        Drive permits overlapping channels and does not offer in-place renewal. A
        retry may therefore leave an extra short-lived channel, but the stored
        channel remains authoritative and duplicate change intake is fingerprinted.
        """

        provider, connection = await self._provider_for_mount(mount.mount_id)
        runtime: DriveRuntime | None = await self._runtime_store.load(
            connection.connection_id
        )
        if (
            runtime is not None
            and runtime.watch_channel_id is not None
            and runtime.watch_resource_id is not None
            and runtime.watch_expiry is not None
            and runtime.watch_expiry > now + renewal_window
        ):
            await self._persist_refreshed_token(connection, provider)
            return False

        page_token = runtime.change_cursor if runtime is not None else None
        if page_token is None:
            page_token = provider.get_start_page_token()
        requested_expiry = now + lifetime
        channel = provider.watch_changes(
            page_token=page_token,
            channel_id=str(uuid4()),
            address=address,
            channel_token=channel_token,
            expiration_millis=int(requested_expiry.timestamp() * 1000),
        )
        expiry = datetime.fromtimestamp(
            channel.expiration_millis / 1000,
            tz=timezone.utc,
        )
        next_runtime = runtime or DriveRuntime(connection_id=connection.connection_id)
        await self._runtime_store.save(
            connection.connection_id,
            next_runtime.model_copy(
                update={
                    "change_cursor": page_token,
                    "watch_channel_id": channel.channel_id,
                    "watch_resource_id": channel.resource_id,
                    "watch_expiry": expiry,
                }
            ),
        )
        await self._persist_refreshed_token(connection, provider)
        return True

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot:
        file_id = change.artifact.source_artifact_id

        scope: DriveTrackingScope | None = await self._tracking_scope_store.load(change.mount_id)
        if scope is None or not scope.contains(file_id):
            raise PermissionDeniedError(
                provider="google_drive",
                safe_message="artifact is outside the tracked Drive selection",
            )

        provider, connection = await self._provider_for_mount(change.mount_id)

        if change.change_type is ChangeType.DELETE:
            await self._persist_refreshed_token(connection, provider)
            return self._unsupported_snapshot(change, resolved_revision=change.revision or "deleted")

        drive_file = provider.get_file(file_id)

        if drive_file.mime_type not in SELECTABLE_MIME_TYPES:
            await self._persist_refreshed_token(connection, provider)
            return self._unsupported_snapshot(
                change, resolved_revision=drive_file.revision_id or "unknown"
            )

        text = provider.read_text(file_id, drive_file.mime_type)
        await self._persist_refreshed_token(connection, provider)

        segment = TextSegment(segment_id="full", text=text, segment_kind=SegmentKind.FULL)
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        receipt = build_access_receipt(
            SourceAccessType.FULL_CONTENT, content_bytes=bytes_of_text(text)
        )

        return SourceSnapshot(
            contract_version="1",
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=SourceType.GOOGLE_DRIVE,
            source_artifact_id=file_id,
            resolved_revision=drive_file.revision_id or "unknown",
            retrieved_at=datetime.now(timezone.utc),
            display_name=drive_file.name,
            logical_path_hint=None,
            mime_type=drive_file.mime_type,
            artifact_kind=self._infer_artifact_kind(drive_file.name),
            content_scope=ContentScope.FULL_TEXT,
            text_segments=[segment],
            checksum=checksum,
            byte_size=bytes_of_text(text),
            source_access_receipt=receipt,
        )

    async def initial_changes(
        self,
        mount: MountRef,
        selected_file_ids: list[str],
    ) -> tuple[SourceChange, ...]:
        """Materialize Picker selections into the canonical change pipeline.

        Drive's changes feed starts *after* ``getStartPageToken``.  It therefore
        cannot discover files that were already selected when a mount was
        created.  Fetching only the Picker-approved IDs preserves ``drive.file``
        while giving each initial file a real provider revision for idempotent
        intake and Worker snapshot validation.
        """
        scope: DriveTrackingScope | None = await self._tracking_scope_store.load(
            mount.mount_id
        )
        if scope is None:
            raise PermissionDeniedError(
                provider="google_drive",
                safe_message="Drive tracking scope is unavailable",
            )
        provider, connection = await self._provider_for_mount(mount.mount_id)
        # 파일을 읽기 **전에** 커서를 확보한다. 순서가 뒤바뀌면 그 사이의 변경이
        # 초기 스냅샷에도, 이후 reconcile 에도 잡히지 않는다.
        await self._ensure_change_cursor(connection, provider)
        now = datetime.now(timezone.utc)
        changes: list[SourceChange] = []
        try:
            for file_id in selected_file_ids:
                if not scope.contains(file_id):
                    raise PermissionDeniedError(
                        provider="google_drive",
                        safe_message="artifact is outside the tracked Drive selection",
                    )
                drive_file = provider.get_file(file_id)
                revision = drive_file.revision_id or drive_file.modified_time or "unknown"
                fingerprint = drive_change_fingerprint(
                    mount_id=mount.mount_id,
                    file_id=file_id,
                    resolved_revision=revision,
                )
                changes.append(
                    SourceChange(
                        contract_version="1",
                        event_id=fingerprint,
                        provider_event_id=None,
                        event_fingerprint=fingerprint,
                        risk_workspace_id=mount.risk_workspace_id,
                        mount_id=mount.mount_id,
                        source_workspace_id=mount.source_workspace_id,
                        source_type=SourceType.GOOGLE_DRIVE,
                        artifact=SourceArtifactRef(
                            source_artifact_id=file_id,
                            display_name=drive_file.name,
                        ),
                        change_type=ChangeType.CREATE,
                        revision=revision,
                        previous_revision=None,
                        observed_at=now,
                        safe_metadata={},
                    )
                )
        finally:
            await self._persist_refreshed_token(connection, provider)
        return tuple(changes)

    def _unsupported_snapshot(self, change: SourceChange, *, resolved_revision: str) -> SourceSnapshot:
        receipt = build_access_receipt(SourceAccessType.METADATA, content_bytes=0)
        return SourceSnapshot(
            contract_version="1",
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=SourceType.GOOGLE_DRIVE,
            source_artifact_id=change.artifact.source_artifact_id,
            resolved_revision=resolved_revision,
            retrieved_at=datetime.now(timezone.utc),
            display_name=change.artifact.display_name,
            logical_path_hint=None,
            mime_type=None,
            artifact_kind=ArtifactKind.UNKNOWN,
            content_scope=ContentScope.UNSUPPORTED,
            text_segments=[],
            checksum=hashlib.sha256(resolved_revision.encode("utf-8")).hexdigest(),
            byte_size=0,
            source_access_receipt=receipt,
        )

    @staticmethod
    def _infer_artifact_kind(name: str) -> ArtifactKind:
        lowered = name.lower()
        if lowered in {"requirements.txt", "package.json"}:
            return ArtifactKind.MANIFEST
        if lowered.endswith(".lock") or lowered.endswith("lockfile"):
            return ArtifactKind.LOCKFILE
        return ArtifactKind.DOCUMENT_TEXT

    async def resolve_original(self, artifact: SourceArtifactRef) -> OriginalSourceLocator:
        provider_url = f"https://drive.google.com/file/d/{artifact.source_artifact_id}/view"
        return OriginalSourceLocator(
            original_source_type=OriginalSourceType.PROVIDER_URL,
            provider_url=provider_url,
            metadata_safe={},
        )

    async def _ensure_change_cursor(self, connection, provider) -> None:
        """mount 시점의 changes 커서를 확보한다.

        ``reconcile()`` 은 저장된 커서가 없으면 ``getStartPageToken()`` 즉 "지금부터"
        로 시작한다. 커서를 첫 reconcile 실행 때 잡으면 **mount 생성부터 그 실행
        사이의 변경이 영구히 유실된다** — 소스를 연결한 직후가 오히려 감지
        사각지대가 된다. 운영에서 실제로 그 구간의 파일 수정이 사라졌다.

        초기 스캔이 현재 상태를 덮으므로, 그 직전 시점을 커서로 두면 이후 변경은
        빠짐없이 잡힌다. 겹치는 변경은 fingerprint 로 무해화된다.
        """
        runtime: DriveRuntime | None = await self._runtime_store.load(
            connection.connection_id
        )
        if runtime is not None and runtime.change_cursor:
            return
        token = provider.get_start_page_token()
        base = runtime or DriveRuntime(connection_id=connection.connection_id)
        await self._runtime_store.save(
            connection.connection_id,
            base.model_copy(update={"change_cursor": token}),
        )

    async def reconcile(self, mount: MountRef, cursor: str | None) -> ReconcileResult:
        scope: DriveTrackingScope | None = await self._tracking_scope_store.load(mount.mount_id)
        tracked_ids = set(scope.selected_file_ids) if scope else set()

        provider, connection = await self._provider_for_mount(mount.mount_id)

        page_token = cursor
        if page_token is None:
            runtime: DriveRuntime | None = await self._runtime_store.load(connection.connection_id)
            page_token = runtime.change_cursor if runtime else None
        if page_token is None:
            page_token = provider.get_start_page_token()

        page = provider.list_changes(page_token)
        await self._persist_refreshed_token(connection, provider)

        now = datetime.now(timezone.utc)
        changes: list[SourceChange] = []
        for item in page.changes:
            if item.file_id not in tracked_ids:
                continue
            change_type = ChangeType.DELETE if item.removed else ChangeType.UPDATE
            revision = item.revision_id or "unknown"
            fingerprint = drive_change_fingerprint(
                mount_id=mount.mount_id, file_id=item.file_id, resolved_revision=revision
            )
            changes.append(
                SourceChange(
                    contract_version="1",
                    event_id=fingerprint,
                    provider_event_id=None,
                    event_fingerprint=fingerprint,
                    risk_workspace_id=mount.risk_workspace_id,
                    mount_id=mount.mount_id,
                    source_workspace_id=mount.source_workspace_id,
                    source_type=SourceType.GOOGLE_DRIVE,
                    artifact=SourceArtifactRef(
                        source_artifact_id=item.file_id,
                        display_name=self._display_name(scope, item.file_id),
                    ),
                    change_type=change_type,
                    revision=item.revision_id,
                    previous_revision=None,
                    observed_at=now,
                    safe_metadata={},
                )
            )

        has_more = page.next_page_token is not None
        next_cursor = page.next_page_token or page.new_start_page_token

        if not has_more and page.new_start_page_token:
            runtime = await self._runtime_store.load(connection.connection_id)
            next_runtime = runtime or DriveRuntime(connection_id=connection.connection_id)
            await self._runtime_store.save(
                connection.connection_id,
                next_runtime.model_copy(
                    update={"change_cursor": page.new_start_page_token}
                ),
            )

        return ReconcileResult(changes=changes, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _display_name(scope: DriveTrackingScope | None, file_id: str) -> str:
        if scope is None:
            return file_id
        metadata = scope.display_metadata_by_file.get(file_id) or {}
        name = metadata.get("name")
        return str(name) if name else file_id
