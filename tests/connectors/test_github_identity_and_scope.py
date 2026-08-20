from __future__ import annotations

import asyncio

import pytest

from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.github.connection_lookup import (
    GitHubConnectionContext,
    InMemoryGitHubConnectionLookup,
)
from ip_risk_agent.connectors.github.identity import (
    decode_github_artifact_id,
    encode_github_artifact_id,
)
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope


def test_identity_roundtrip():
    encoded = encode_github_artifact_id(owner="acme", repo="widgets", branch="main", path="src/a.py")
    decoded = decode_github_artifact_id(encoded)
    assert decoded.owner == "acme"
    assert decoded.repo == "widgets"
    assert decoded.branch == "main"
    assert decoded.path == "src/a.py"


def test_identity_decode_malformed_raises():
    with pytest.raises(ValueError):
        decode_github_artifact_id("not-valid-base64!!!")


def test_scope_includes_matching_path():
    scope = GitHubTrackingScope(
        mount_id="m1", owner="acme", repo="widgets", default_branch="main", tracked_branch="main",
        include_patterns=["src/**", "package*.json"],
    )
    assert scope.is_tracked("src/deep/a.py") is True
    assert scope.is_tracked("package-lock.json") is True


def test_scope_excludes_win_over_include():
    scope = GitHubTrackingScope(
        mount_id="m1", owner="acme", repo="widgets", default_branch="main", tracked_branch="main",
        include_patterns=["**"],
        exclude_patterns=["customer-data/**"],
    )
    assert scope.is_tracked("customer-data/secret.csv") is False
    assert scope.is_tracked("src/a.py") is True


def test_scope_empty_include_means_track_everything_not_excluded():
    scope = GitHubTrackingScope(
        mount_id="m1", owner="acme", repo="widgets", default_branch="main", tracked_branch="main",
    )
    assert scope.is_tracked("anything/at/all.py") is True


def test_connection_lookup_register_then_resolve():
    async def scenario():
        lookup = InMemoryGitHubConnectionLookup()
        lookup.register("mount-1", GitHubConnectionContext(installation_id="inst-1"))
        resolved = await lookup.resolve("mount-1")
        assert resolved.installation_id == "inst-1"

    asyncio.run(scenario())


def test_connection_lookup_unknown_mount_raises_not_found():
    async def scenario():
        lookup = InMemoryGitHubConnectionLookup()
        with pytest.raises(NotFoundError):
            await lookup.resolve("never-registered")

    asyncio.run(scenario())
