from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from iprisk_contracts.common import ChangeType, MountRef, SourceArtifactRef, SourceType
from iprisk_contracts.source_change import SourceChange

from ip_risk_agent.connectors.common.errors import PermissionDeniedError
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.github.adapter import GitHubAdapter
from ip_risk_agent.connectors.github.connection_lookup import (
    GitHubConnectionContext,
    InMemoryGitHubConnectionLookup,
)
from ip_risk_agent.connectors.github.identity import encode_github_artifact_id
from ip_risk_agent.connectors.github.models import GitHubFileContent, GitHubInstallationToken
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope


class FakeGitHubProvider:
    def __init__(self, files: dict | None = None) -> None:
        self._files = files or {}
        self.token_fetched = False

    async def get_installation_token(self) -> GitHubInstallationToken:
        self.token_fetched = True
        return GitHubInstallationToken(token="ghs_fake", expires_at="2026-01-01T00:00:00Z")

    async def get_default_branch(self, owner: str, repo: str) -> str:
        return "main"

    async def get_commit(self, owner: str, repo: str, sha: str):
        raise NotImplementedError

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> GitHubFileContent:
        return self._files[path]


class FakeGitHubProviderFactory:
    def __init__(self, provider: FakeGitHubProvider) -> None:
        self._provider = provider

    def create(self, installation_id: str) -> FakeGitHubProvider:
        return self._provider


async def _build_adapter(provider: FakeGitHubProvider, *, include_patterns=None, exclude_patterns=None):
    lookup = InMemoryGitHubConnectionLookup()
    lookup.register("mount-1", GitHubConnectionContext(installation_id="inst-1"))
    scope_store = InMemoryRuntimeStore()
    await scope_store.save(
        "mount-1",
        GitHubTrackingScope(
            mount_id="mount-1", owner="acme", repo="widgets", default_branch="main", tracked_branch="main",
            include_patterns=include_patterns or [], exclude_patterns=exclude_patterns or [],
        ),
    )
    adapter = GitHubAdapter(
        provider_factory=FakeGitHubProviderFactory(provider),
        connection_lookup=lookup,
        tracking_scope_store=scope_store,
    )
    return adapter


def _mount() -> MountRef:
    return MountRef(risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1", source_type=SourceType.GITHUB)


def _change(path: str, *, change_type: ChangeType = ChangeType.UPDATE, revision: str | None = "sha1") -> SourceChange:
    artifact_id = encode_github_artifact_id(owner="acme", repo="widgets", branch="main", path=path)
    return SourceChange(
        contract_version="1", event_id="e1", event_fingerprint="fp1",
        risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1",
        source_type=SourceType.GITHUB,
        artifact=SourceArtifactRef(source_artifact_id=artifact_id, display_name=path, path_hint=path),
        change_type=change_type, revision=revision,
        observed_at=datetime.now(timezone.utc), safe_metadata={},
    )


def test_fetch_snapshot_returns_full_text_for_tracked_file():
    async def scenario():
        provider = FakeGitHubProvider(files={"src/a.py": GitHubFileContent(path="src/a.py", sha="blobsha", text="print(1)", size=8)})
        adapter = await _build_adapter(provider, include_patterns=["src/**"])

        snapshot = await adapter.fetch_snapshot(_change("src/a.py"))

        assert snapshot.content_scope.value == "FULL_TEXT"
        assert snapshot.text_segments[0].text == "print(1)"
        assert snapshot.artifact_kind.value == "SOURCE_CODE"

    asyncio.run(scenario())


def test_fetch_snapshot_rejects_excluded_path():
    async def scenario():
        provider = FakeGitHubProvider()
        adapter = await _build_adapter(provider, include_patterns=["**"], exclude_patterns=["customer-data/**"])

        with pytest.raises(PermissionDeniedError):
            await adapter.fetch_snapshot(_change("customer-data/secret.csv"))

    asyncio.run(scenario())


def test_fetch_snapshot_delete_change_returns_unsupported():
    async def scenario():
        provider = FakeGitHubProvider()
        adapter = await _build_adapter(provider, include_patterns=["src/**"])

        snapshot = await adapter.fetch_snapshot(_change("src/a.py", change_type=ChangeType.DELETE))

        assert snapshot.content_scope.value == "UNSUPPORTED"

    asyncio.run(scenario())


def test_fetch_snapshot_oversized_file_returns_unsupported():
    async def scenario():
        big_text = "x" * 2_000_000
        provider = FakeGitHubProvider(files={"data/big.txt": GitHubFileContent(path="data/big.txt", sha="s", text=big_text, size=2_000_000)})
        adapter = await _build_adapter(provider, include_patterns=["data/**"])

        snapshot = await adapter.fetch_snapshot(_change("data/big.txt"))

        assert snapshot.content_scope.value == "UNSUPPORTED"

    asyncio.run(scenario())


def test_resolve_original_builds_blob_url():
    async def scenario():
        adapter = await _build_adapter(FakeGitHubProvider())
        artifact_id = encode_github_artifact_id(owner="acme", repo="widgets", branch="main", path="src/a.py")

        locator = await adapter.resolve_original(SourceArtifactRef(source_artifact_id=artifact_id, display_name="a.py"))

        assert locator.original_source_type.value == "PROVIDER_URL"
        assert locator.provider_url == "https://github.com/acme/widgets/blob/main/src/a.py"

    asyncio.run(scenario())


def test_health_returns_healthy():
    async def scenario():
        adapter = await _build_adapter(FakeGitHubProvider())
        health = await adapter.health(_mount())
        assert health.status.value == "HEALTHY"

    asyncio.run(scenario())


def test_health_offline_when_installation_not_registered():
    async def scenario():
        lookup = InMemoryGitHubConnectionLookup()
        scope_store = InMemoryRuntimeStore()
        adapter = GitHubAdapter(
            provider_factory=FakeGitHubProviderFactory(FakeGitHubProvider()),
            connection_lookup=lookup,
            tracking_scope_store=scope_store,
        )
        health = await adapter.health(_mount())
        assert health.status.value == "OFFLINE"

    asyncio.run(scenario())
