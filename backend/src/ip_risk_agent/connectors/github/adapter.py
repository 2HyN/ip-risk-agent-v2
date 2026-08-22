"""Master Spec 9번 SourceAdapter 계약의 GitHub 구현.

reconcile()은 다음 단계(B-3, webhook 처리와 함께)에서 구현한다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol

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
from iprisk_contracts.source_snapshot import SourceSnapshot

from ..common.adapter_support import build_access_receipt, bytes_of_text
from ..common.segmentation import split_document
from ..common.fingerprint import github_change_fingerprint
from ..common.errors import (
    AuthRequiredError,
    NotFoundError,
    PermissionDeniedError,
    SourceConnectorError,
)
from ..common.ipriskignore import is_denied_by_ipriskignore, parse_ipriskignore
from .connection_lookup import GitHubConnectionContext, GitHubConnectionLookup
from .identity import decode_github_artifact_id, encode_github_artifact_id
from .models import GitHubProvider
from .tracking_scope import GitHubTrackingScope

MAX_FILE_BYTES = 1_000_000

_CODE_EXTENSIONS = {".py", ".js", ".ts", ".java", ".go", ".c", ".h", ".cpp", ".rs"}
_DOC_EXTENSIONS = {".md", ".txt", ".rst"}


class GitHubProviderFactory(Protocol):
    def create(self, installation_id: str) -> GitHubProvider: ...


class GitHubAdapter:
    source_type = SourceType.GITHUB

    def __init__(
        self,
        *,
        provider_factory: GitHubProviderFactory,
        connection_lookup: GitHubConnectionLookup,
        tracking_scope_store,
    ) -> None:
        self._provider_factory = provider_factory
        self._connection_lookup = connection_lookup
        self._tracking_scope_store = tracking_scope_store

    async def _provider_for_mount(self, mount_id: str) -> tuple[GitHubProvider, GitHubConnectionContext]:
        connection = await self._connection_lookup.resolve(mount_id)
        provider = self._provider_factory.create(connection.installation_id)
        return provider, connection

    @staticmethod
    async def _fetch_source_ignore_patterns(
        provider: GitHubProvider, owner: str, repo: str, branch: str
    ) -> list[str]:
        """repo 루트의 .ipriskignore를 읽는다. 없으면 빈 목록(제약 없음) —
        optional deny source이지 필수 파일이 아니다 (Agent2 Spec §18)."""

        try:
            content = await provider.get_file_content(owner, repo, ".ipriskignore", branch)
        except NotFoundError:
            return []
        return parse_ipriskignore(content.text)

    async def health(self, mount: MountRef) -> SourceHealth:
        try:
            provider, _ = await self._provider_for_mount(mount.mount_id)
            await provider.get_installation_token()
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

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot:
        try:
            identity = decode_github_artifact_id(change.artifact.source_artifact_id)
        except ValueError as exc:
            raise PermissionDeniedError(
                provider="github", safe_message="malformed github artifact id"
            ) from exc

        scope: GitHubTrackingScope | None = await self._tracking_scope_store.load(change.mount_id)
        if scope is None or not scope.is_tracked(identity.path):
            raise PermissionDeniedError(
                provider="github", safe_message="artifact is outside the tracked path scope"
            )

        provider, _ = await self._provider_for_mount(change.mount_id)

        source_ignore_patterns = await self._fetch_source_ignore_patterns(
            provider, identity.owner, identity.repo, identity.branch
        )
        if is_denied_by_ipriskignore(identity.path, source_ignore_patterns):
            raise PermissionDeniedError(
                provider="github", safe_message="artifact is denied by source-level .ipriskignore"
            )

        if change.change_type is ChangeType.DELETE:
            return self._unsupported_snapshot(change, resolved_revision=change.revision or "deleted")

        file_content = await provider.get_file_content(
            identity.owner, identity.repo, identity.path, identity.branch
        )

        if file_content.size > MAX_FILE_BYTES:
            return self._unsupported_snapshot(
                change, resolved_revision=change.revision or file_content.sha
            )

        segments = split_document(file_content.text)
        checksum = hashlib.sha256(file_content.text.encode("utf-8")).hexdigest()
        receipt = build_access_receipt(
            SourceAccessType.FULL_CONTENT, content_bytes=bytes_of_text(file_content.text)
        )

        return SourceSnapshot(
            contract_version="1",
            risk_workspace_id=change.risk_workspace_id,
            mount_id=change.mount_id,
            source_workspace_id=change.source_workspace_id,
            source_type=SourceType.GITHUB,
            source_artifact_id=change.artifact.source_artifact_id,
            resolved_revision=change.revision or file_content.sha,
            retrieved_at=datetime.now(timezone.utc),
            display_name=identity.path,
            logical_path_hint=identity.path,
            mime_type=None,
            artifact_kind=self._infer_artifact_kind(identity.path),
            content_scope=ContentScope.FULL_TEXT,
            text_segments=segments,
            checksum=checksum,
            byte_size=bytes_of_text(file_content.text),
            source_access_receipt=receipt,
        )

    async def initial_changes(self, mount: MountRef) -> tuple[SourceChange, ...]:
        scope: GitHubTrackingScope | None = await self._tracking_scope_store.load(
            mount.mount_id
        )
        if scope is None:
            raise PermissionDeniedError(
                provider="github",
                safe_message="GitHub tracking scope is unavailable",
            )
        provider, _ = await self._provider_for_mount(mount.mount_id)
        ignored = await self._fetch_source_ignore_patterns(
            provider,
            scope.owner,
            scope.repo,
            scope.tracked_branch,
        )
        files = await provider.list_repository_files(
            scope.owner,
            scope.repo,
            scope.tracked_branch,
        )
        repository_id = f"{scope.owner}/{scope.repo}"
        observed_at = datetime.now(timezone.utc)
        changes: list[SourceChange] = []
        for file in files:
            if not scope.is_tracked(file.path):
                continue
            if is_denied_by_ipriskignore(file.path, ignored):
                continue
            fingerprint = github_change_fingerprint(
                mount_id=mount.mount_id,
                repository_id=repository_id,
                tracked_branch=scope.tracked_branch,
                commit_sha=file.sha,
                changed_path=file.path,
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
                    source_type=SourceType.GITHUB,
                    artifact=SourceArtifactRef(
                        source_artifact_id=encode_github_artifact_id(
                            owner=scope.owner,
                            repo=scope.repo,
                            branch=scope.tracked_branch,
                            path=file.path,
                        ),
                        display_name=file.path.rsplit("/", 1)[-1],
                        path_hint=file.path,
                    ),
                    change_type=ChangeType.CREATE,
                    revision=file.sha,
                    previous_revision=None,
                    observed_at=observed_at,
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
            source_type=SourceType.GITHUB,
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
    def _infer_artifact_kind(path: str) -> ArtifactKind:
        lowered = path.lower()
        name = lowered.rsplit("/", 1)[-1]
        # 읽을 수 있는 이름만 의존성으로 본다. 예전에는 setup.py 를 의존성으로
        # 분류했는데 파서가 없어, License 도 Patent 도 맡지 못한 채 계약 위반으로
        # 실패했다. setup.py 는 아래에서 소스 코드로 분류된다.
        found = dependency_format(name)
        if found is not None:
            return ArtifactKind.LOCKFILE if found.is_lockfile else ArtifactKind.MANIFEST
        for ext in _CODE_EXTENSIONS:
            if name.endswith(ext):
                return ArtifactKind.SOURCE_CODE
        for ext in _DOC_EXTENSIONS:
            if name.endswith(ext):
                return ArtifactKind.DOCUMENT_TEXT
        return ArtifactKind.UNKNOWN

    async def resolve_original(self, artifact: SourceArtifactRef) -> OriginalSourceLocator:
        try:
            identity = decode_github_artifact_id(artifact.source_artifact_id)
        except ValueError as exc:
            raise PermissionDeniedError(
                provider="github", safe_message="malformed github artifact id"
            ) from exc

        provider_url = (
            f"https://github.com/{identity.owner}/{identity.repo}/blob/{identity.branch}/{identity.path}"
        )
        return OriginalSourceLocator(
            original_source_type=OriginalSourceType.PROVIDER_URL,
            provider_url=provider_url,
            metadata_safe={},
        )

    async def reconcile(self, mount: MountRef, cursor: str | None) -> ReconcileResult:
        # Agent 2 Spec 43번: GitHub는 webhook이 주 경로다. reconcile은
        # 최소한 안전한 no-op/capability 표현만 만족하면 된다.
        return ReconcileResult(changes=[], next_cursor=cursor, has_more=False)
