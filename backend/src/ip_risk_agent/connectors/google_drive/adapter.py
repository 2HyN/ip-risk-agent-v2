"""Master Spec 9번 SourceAdapter 계약의 Drive 구현.

models.py의 DriveProvider Protocol에만 의존한다 (client.py를 직접
import하지 않음) — 그래서 googleapiclient 설치 여부와 무관하게 지금
바로 테스트할 수 있다. 운영 시엔 client.GoogleDriveProviderFactory가,
테스트에선 Fake factory가 provider_factory로 주입된다.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
from ip_risk_agent.core.artifacts.dependency_files import dependency_format
from ip_risk_agent.core.artifacts.naming import display_name_for
from ip_risk_agent.core.artifacts.text_files import (
    NON_COMMITTAL_MIME_TYPES,
    is_text_like,
    mime_is_textual,
    text_kind,
)
from iprisk_contracts.source_snapshot import SourceSnapshot

from ..common.adapter_support import build_access_receipt, bytes_of_text
from ..common.segmentation import segments_for
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
from .folders import (
    MAX_FOLDER_DEPTH,
    MAX_FOLDER_ITEMS,
    is_inside_folder,
    list_folder_files,
)
from .paths import resolve_path_hint

logger = logging.getLogger(__name__)
from .tracking_scope import DriveTrackingScope


class DriveProviderFactory(Protocol):
    """D1 — provider 를 만드는 데 토큰이 필요 없다.

    접근이 폴더 공유에서 오므로 마운트마다 다른 자격증명이 없다. 하나의 서비스
    계정이 공유받은 것만 본다 (`service_account.py`).
    """

    def create(self) -> DriveProvider: ...


def _is_readable(mime_type: str, name: str) -> bool:
    """이 Drive 파일을 읽어 볼 것인가.

    예전에는 ``SELECTABLE_MIME_TYPES`` 네 가지만 통과했다. 그래서 ``.py`` 는
    ``text/x-python`` 으로 와도 떨어졌고, ``.yaml`` · ``.csv`` 도 마찬가지였다.
    GitHub 과 Local 은 이름만 보고 판단하므로 **같은 파일이 소스마다 다른 대접**을
    받았고, 폴더 마운트가 열리면 (§6.1) 그 차이가 그대로 누락이 된다.

    규칙은 게이트와 같다 (``security_gate.service._mime_is_denied``).
    """
    if mime_type in SELECTABLE_MIME_TYPES or mime_is_textual(mime_type):
        return True
    # mime 이 판단을 미뤘을 때만 이름이 대신한다. 이미지라고 주장하는 값은 뒤집지 않는다.
    normalized = (mime_type or "").split(";", 1)[0].strip().casefold()
    return normalized in NON_COMMITTAL_MIME_TYPES and is_text_like(name)



class GoogleDriveAdapter:
    source_type = SourceType.GOOGLE_DRIVE

    def __init__(
        self,
        *,
        provider_factory: DriveProviderFactory,
        connection_lookup: DriveConnectionLookup,
        tracking_scope_store,
        runtime_store,
    ) -> None:
        self._provider_factory = provider_factory
        self._connection_lookup = connection_lookup
        self._tracking_scope_store = tracking_scope_store
        self._runtime_store = runtime_store

    async def _provider_for_mount(
        self, mount_id: str
    ) -> tuple[DriveProvider, DriveConnectionContext]:
        """연결은 여전히 찾는다 — 변경 커서를 그 id 로 보관하기 때문이다.

        찾지 않는 것은 **자격증명**이다. 마운트마다 다른 토큰이 없고, 보관할 것도
        없다 (D1).
        """
        connection = await self._connection_lookup.resolve(mount_id)
        return self._provider_factory.create(), connection

    async def health(self, mount: MountRef) -> SourceHealth:
        try:
            provider, connection = await self._provider_for_mount(mount.mount_id)
            provider.get_access_token()
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
        return True

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot:
        file_id = change.artifact.source_artifact_id

        scope: DriveTrackingScope | None = await self._tracking_scope_store.load(change.mount_id)
        if scope is None:
            raise PermissionDeniedError(
                provider="google_drive",
                safe_message="Drive tracking scope is unavailable",
            )

        provider, connection = await self._provider_for_mount(change.mount_id)

        # 명단이 아니라 **지금 어디에 있는지**를 묻는다. 그래서 폴더에 넣으면 잡히고
        # 빼면 빠진다 (§6.1 · 1-F).
        if not is_inside_folder(provider, file_id, scope.folder_id):
            raise PermissionDeniedError(
                provider="google_drive",
                safe_message="artifact is outside the tracked Drive folder",
            )

        if change.change_type is ChangeType.DELETE:
            return self._unsupported_snapshot(change, resolved_revision=change.revision or "deleted")

        drive_file = provider.get_file(file_id)

        # mime 이 통과시키는 것은 네 가지뿐이라 `.py`·`.yaml`·`.csv` 가 여기서
        # 사라졌다. 그런데 **이름이 텍스트라고 말하면 읽어 볼 수 있다.** GitHub 과
        # Local 은 이름만으로 판단하므로, 이 문만 좁으면 같은 파일이 소스에 따라
        # 검사를 받기도 하고 안 받기도 한다. 폴더 마운트가 열리면 (§6.1) 그 차이가
        # 그대로 누락이 된다.
        if not _is_readable(drive_file.mime_type, drive_file.name):
            return self._unsupported_snapshot(
                change, resolved_revision=drive_file.revision_id or "unknown"
            )

        try:
            text = provider.read_text(file_id, drive_file.mime_type)
        except UnicodeDecodeError:
            # 이름이나 mime 은 텍스트라고 했는데 알맹이가 아니었다 (§6.2).
            return self._unsupported_snapshot(
                change, resolved_revision=drive_file.revision_id or "unreadable"
            )

        segments = segments_for(
            text, self._infer_artifact_kind(drive_file.name, drive_file.mime_type)
        )
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
            display_name=display_name_for(drive_file.name),
            # 예전에는 `None` 이라 Drive 아티팩트의 `logical_path` 가 `별칭/파일이름`
            # 으로 평평했다. 폴더가 다른 같은 이름의 파일이 구별되지 않고, UI 트리를
            # 만들 근거가 없었다 (§6.1).
            logical_path_hint=resolve_path_hint(
                provider, file_id, drive_file.name, drive_file.parents
            ),
            mime_type=drive_file.mime_type,
            artifact_kind=self._infer_artifact_kind(drive_file.name, drive_file.mime_type),
            content_scope=ContentScope.FULL_TEXT,
            text_segments=segments,
            checksum=checksum,
            byte_size=bytes_of_text(text),
            source_access_receipt=receipt,
        )

    async def initial_changes(
        self,
        mount: MountRef,
        selected_file_ids: list[str] | None = None,
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
        listing = list_folder_files(provider, scope.folder_id)
        if listing.truncated:
            # 조용히 자르면 "전부 검사했다" 로 읽힌다 (§6.1).
            logger.warning(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event": "drive_folder_listing_truncated",
                        "mount_id": mount.mount_id,
                        "item_count": len(listing.files),
                        "max_items": MAX_FOLDER_ITEMS,
                        "max_depth": MAX_FOLDER_DEPTH,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )

        for drive_file in listing.files:
            file_id = drive_file.file_id
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
                        display_name=display_name_for(drive_file.name),
                    ),
                    change_type=ChangeType.CREATE,
                    revision=revision,
                    previous_revision=None,
                    observed_at=now,
                    safe_metadata={},
                )
            )
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
            # 지어내지 않는다. 변경이 들고 온 값이 등록에 쓰인 그 값이고, 없으면
            # `None` 이 맞다 — 지운 파일은 메타데이터를 읽을 수 없다.
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
    def _infer_artifact_kind(name: str, mime_type: str | None = None) -> ArtifactKind:
        # 의존성 판정은 커넥터마다 다를 이유가 없다. 세 커넥터가 각자 목록을 들고
        # 있어 같은 pyproject.toml 이 Drive 에서는 Patent, GitHub 에서는 License
        # 검사를 받았다.
        found = dependency_format(name)
        if found is not None:
            return ArtifactKind.LOCKFILE if found.is_lockfile else ArtifactKind.MANIFEST
        # 예전에는 나머지를 **전부 문서**로 봤다. 사용자가 하나씩 골라 붙이니 고른
        # 것은 보겠다는 뜻이라는 논리였는데, 그 결과 같은 `main.py` 가 GitHub 에서는
        # 소스 코드로, Drive 에서는 문서로 분석됐다. 폴더 마운트가 열리면 (§6.1)
        # 고른다는 전제 자체가 없어진다.
        kind = text_kind(name)
        if kind is not None:
            return kind
        # 확장자로는 모르겠는데 mime 이 텍스트라고 말한다. Google 문서와
        # `text/plain` 이 여기 해당한다 — 확장자가 없는 경우가 많다.
        if mime_type in SELECTABLE_MIME_TYPES:
            return ArtifactKind.DOCUMENT_TEXT
        return ArtifactKind.UNKNOWN

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

        provider, connection = await self._provider_for_mount(mount.mount_id)
        # 한 번 훑는 동안 조상 조회를 재사용한다. 같은 폴더가 여러 파일의 조상이다.
        membership_cache: dict[str, tuple[str, ...]] = {}

        page_token = cursor
        if page_token is None:
            runtime: DriveRuntime | None = await self._runtime_store.load(connection.connection_id)
            page_token = runtime.change_cursor if runtime else None
        if page_token is None:
            page_token = provider.get_start_page_token()

        page = provider.list_changes(page_token)

        now = datetime.now(timezone.utc)
        changes: list[SourceChange] = []
        # 같은 폴더가 여러 파일의 조상이다. 한 번 훑는 동안 재사용한다.
        path_cache: dict[str, tuple[str, tuple[str, ...]]] = {}
        for item in page.changes:
            if scope is None:
                continue
            if item.removed:
                # 이탈은 파일이 SA 에게서 통째로 사라진 모양으로 온다 (실측 §2.1.1).
                # 그때는 부모를 물을 수 없으므로 소속을 확인할 방법이 없다. 우리
                # 폴더의 파일이었는지는 등록된 아티팩트가 안다 — Control 이 모르는
                # id 면 그냥 지나간다.
                pass
            elif not is_inside_folder(
                provider, item.file_id, scope.folder_id, cache=membership_cache
            ):
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
                        # 아티팩트의 `logical_path` 를 정하는 곳이 여기다. 가져오기가
                        # 내는 값과 **같아야** 한다 — 다르면 게이트가
                        # `CANONICAL_CONTEXT_MISMATCH` 로 거부한다.
                        path_hint=self._path_hint(provider, item.file_id, path_cache),
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
    def _path_hint(
        provider,
        file_id: str,
        cache: dict[str, tuple[str, tuple[str, ...]]],
    ) -> str | None:
        """대조가 쓰는 경로. 읽지 못하면 ``None`` 이다.

        지운 파일은 메타데이터를 못 읽는다. 그때 경로를 지어내면 등록된 것과 달라져
        게이트가 거부한다. 모르면 안 넘기는 것이 맞다 — 이미 등록된 아티팩트의 경로는
        그대로 남는다.
        """
        try:
            found = provider.get_file(file_id)
        except Exception:  # noqa: BLE001 - 지운 파일은 읽히지 않는다
            return None
        return resolve_path_hint(
            provider, file_id, found.name, found.parents, cache=cache
        )

    @staticmethod
    def _display_name(scope: DriveTrackingScope | None, file_id: str) -> str:
        if scope is None:
            return file_id
        metadata = scope.display_metadata_by_file.get(file_id) or {}
        name = metadata.get("name")
        return str(name) if name else file_id
