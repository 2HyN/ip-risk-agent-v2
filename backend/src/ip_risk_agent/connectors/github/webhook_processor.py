"""GitHub push webhook -> SourceChange 변환.

SourceAdapter 계약 밖의 클래스다 (webhook 처리는 frozen contract에 없음).
나중에 실제 /webhooks/github 라우터가 이 클래스를 호출하는 구조가 될 것.

payload의 added/removed/modified 목록을 그대로 믿지 않고, provider.get_commit()을
다시 호출해서 GitHub API가 주는 정확한 renamed/previous_filename을 사용한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from iprisk_contracts.common import ChangeType, MountRef, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange

from ..common.errors import InvalidWebhookError, NotFoundError
from ..common.fingerprint import github_change_fingerprint
from ..common.ipriskignore import is_denied_by_ipriskignore, parse_ipriskignore
from ..common.runtime_store import GitHubRuntime, WebhookStatus
from .connection_lookup import GitHubConnectionContext, GitHubConnectionLookup
from .identity import encode_github_artifact_id
from .models import GitHubProvider
from .tracking_scope import GitHubTrackingScope
from .webhook import verify_webhook_signature


class GitHubProviderFactory(Protocol):
    def create(self, installation_id: str) -> GitHubProvider: ...


class GitHubWebhookProcessor:
    def __init__(
        self,
        *,
        provider_factory: GitHubProviderFactory,
        connection_lookup: GitHubConnectionLookup,
        tracking_scope_store,
        runtime_store,
        webhook_secret: str,
    ) -> None:
        self._provider_factory = provider_factory
        self._connection_lookup = connection_lookup
        self._tracking_scope_store = tracking_scope_store
        self._runtime_store = runtime_store
        self._webhook_secret = webhook_secret

    async def _provider_for_mount(self, mount_id: str) -> tuple[GitHubProvider, GitHubConnectionContext]:
        connection = await self._connection_lookup.resolve(mount_id)
        provider = self._provider_factory.create(connection.installation_id)
        return provider, connection

    @staticmethod
    async def _fetch_source_ignore_patterns(
        provider: GitHubProvider, owner: str, repo: str, branch: str
    ) -> list[str]:
        try:
            content = await provider.get_file_content(owner, repo, ".ipriskignore", branch)
        except NotFoundError:
            return []
        return parse_ipriskignore(content.text)

    async def process_push_event(
        self,
        mount: MountRef,
        *,
        raw_body: bytes,
        signature_header: str | None,
        delivery_id: str,
        payload: dict,
    ) -> list[SourceChange]:
        if not verify_webhook_signature(raw_body, signature_header, self._webhook_secret):
            raise InvalidWebhookError(provider="github", safe_message="invalid webhook signature")

        scope: GitHubTrackingScope | None = await self._tracking_scope_store.load(mount.mount_id)
        if scope is None:
            raise NotFoundError(
                provider="github", safe_message=f"no tracking scope registered for mount {mount.mount_id}"
            )

        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/")
        if branch != scope.tracked_branch:
            return []

        runtime: GitHubRuntime | None = await self._runtime_store.load(mount.mount_id)
        if runtime is not None and runtime.last_seen_delivery_id == delivery_id:
            return []

        provider, connection = await self._provider_for_mount(mount.mount_id)
        repository_id = f"{scope.owner}/{scope.repo}"
        commit_shas = [c["id"] for c in payload.get("commits", []) if isinstance(c, dict) and c.get("id")]

        source_ignore_patterns = await self._fetch_source_ignore_patterns(
            provider, scope.owner, scope.repo, branch
        )

        changes: list[SourceChange] = []
        now = datetime.now(timezone.utc)
        for sha in commit_shas:
            commit = await provider.get_commit(scope.owner, scope.repo, sha)
            for file in commit.files:
                if is_denied_by_ipriskignore(file.filename, source_ignore_patterns):
                    continue
                if file.status == "renamed":
                    old_tracked = bool(file.previous_filename) and scope.is_tracked(file.previous_filename)
                    if not scope.is_tracked(file.filename) and not old_tracked:
                        continue
                    change_type = ChangeType.MOVE
                elif file.status == "removed":
                    if not scope.is_tracked(file.filename):
                        continue
                    change_type = ChangeType.DELETE
                elif file.status in ("added", "copied"):
                    if not scope.is_tracked(file.filename):
                        continue
                    change_type = ChangeType.CREATE
                else:
                    if not scope.is_tracked(file.filename):
                        continue
                    change_type = ChangeType.UPDATE

                fingerprint = github_change_fingerprint(
                    mount_id=scope.mount_id,
                    repository_id=repository_id,
                    tracked_branch=branch,
                    commit_sha=sha,
                    changed_path=file.filename,
                )
                artifact_id = encode_github_artifact_id(
                    owner=scope.owner, repo=scope.repo, branch=branch, path=file.filename
                )

                previous_artifact = None
                if file.status == "renamed" and file.previous_filename:
                    previous_artifact_id = encode_github_artifact_id(
                        owner=scope.owner, repo=scope.repo, branch=branch, path=file.previous_filename
                    )
                    previous_artifact = SourceArtifactRef(
                        source_artifact_id=previous_artifact_id,
                        display_name=file.previous_filename,
                        path_hint=file.previous_filename,
                    )

                changes.append(
                    SourceChange(
                        contract_version="1",
                        event_id=fingerprint,
                        provider_event_id=delivery_id,
                        event_fingerprint=fingerprint,
                        risk_workspace_id=mount.risk_workspace_id,
                        mount_id=mount.mount_id,
                        source_workspace_id=mount.source_workspace_id,
                        source_type=SourceType.GITHUB,
                        artifact=SourceArtifactRef(
                            source_artifact_id=artifact_id,
                            display_name=file.filename,
                            path_hint=file.filename,
                        ),
                        previous_artifact=previous_artifact,
                        change_type=change_type,
                        revision=sha,
                        previous_revision=None,
                        observed_at=now,
                        safe_metadata={},
                    )
                )

        await self._runtime_store.save(
            mount.mount_id,
            GitHubRuntime(
                connection_id=connection.installation_id,
                installation_id=connection.installation_id,
                repository_id=repository_id,
                tracked_branch=branch,
                webhook_status=WebhookStatus.ACTIVE,
                last_seen_delivery_id=delivery_id,
            ),
        )

        return changes
