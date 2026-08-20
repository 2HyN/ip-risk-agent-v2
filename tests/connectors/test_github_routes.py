from __future__ import annotations

import hashlib
import hmac
import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from iprisk_contracts.common import MountRef, SourceType

from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.common.change_sink import InMemorySourceChangeSink
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.github.connection_lookup import (
    GitHubConnectionContext,
    InMemoryGitHubConnectionLookup,
)
from ip_risk_agent.connectors.github.models import GitHubCommit, GitHubCommitFile
from ip_risk_agent.connectors.github.mount_resolver import InMemoryGitHubMountResolver
from ip_risk_agent.connectors.github.routes import create_github_webhook_router
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope
from ip_risk_agent.connectors.github.webhook_processor import GitHubWebhookProcessor

SECRET = "route-test-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


class FakeGitHubProvider:
    def __init__(self, commits: dict[str, GitHubCommit]) -> None:
        self._commits = commits

    async def get_installation_token(self):
        raise NotImplementedError

    async def get_default_branch(self, owner, repo):
        raise NotImplementedError

    async def get_commit(self, owner: str, repo: str, sha: str) -> GitHubCommit:
        return self._commits[sha]

    async def get_file_content(self, owner, repo, path, ref):
        raise NotFoundError(provider="github", safe_message=f"{path} not found")


class FakeGitHubProviderFactory:
    def __init__(self, provider: FakeGitHubProvider) -> None:
        self._provider = provider

    def create(self, installation_id: str) -> FakeGitHubProvider:
        return self._provider


def _mount() -> MountRef:
    return MountRef(risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1", source_type=SourceType.GITHUB)


async def _build_client(commits: dict[str, GitHubCommit], *, register_repo: bool = True):
    provider = FakeGitHubProvider(commits=commits)
    connection_lookup = InMemoryGitHubConnectionLookup()
    connection_lookup.register("mount-1", GitHubConnectionContext(installation_id="inst-1"))
    scope_store = InMemoryRuntimeStore()
    await scope_store.save(
        "mount-1",
        GitHubTrackingScope(
            mount_id="mount-1", owner="acme", repo="widgets", default_branch="main", tracked_branch="main",
            include_patterns=["src/**"],
        ),
    )
    runtime_store = InMemoryRuntimeStore()
    processor = GitHubWebhookProcessor(
        provider_factory=FakeGitHubProviderFactory(provider),
        connection_lookup=connection_lookup,
        tracking_scope_store=scope_store,
        runtime_store=runtime_store,
        webhook_secret=SECRET,
    )
    mount_resolver = InMemoryGitHubMountResolver()
    if register_repo:
        mount_resolver.register("acme", "widgets", [_mount()])
    sink = InMemorySourceChangeSink()

    router = create_github_webhook_router(webhook_processor=processor, mount_resolver=mount_resolver, change_sink=sink)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, sink


def _push_body(*, ref: str = "refs/heads/main", commit_shas: list[str] | None = None) -> bytes:
    payload = {
        "ref": ref,
        "repository": {"full_name": "acme/widgets"},
        "commits": [{"id": sha} for sha in (commit_shas or ["sha1"])],
    }
    return json.dumps(payload).encode("utf-8")


def test_valid_push_persists_change_via_sink():
    import asyncio

    async def scenario():
        commit = GitHubCommit(sha="sha1", files=[GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None)])
        client, sink = await _build_client({"sha1": commit})

        body = _push_body()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": _sign(body),
                "X-GitHub-Delivery": "d1",
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        assert response.json()["changes_persisted"] == 1
        assert len(sink.received) == 1
        assert sink.received[0].artifact.display_name == "src/a.py"

    asyncio.run(scenario())


def test_non_push_event_is_ignored():
    import asyncio

    async def scenario():
        client, sink = await _build_client({})

        body = _push_body()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": _sign(body),
                "X-GitHub-Delivery": "d1",
                "X-GitHub-Event": "pull_request",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert sink.received == []

    asyncio.run(scenario())


def test_invalid_signature_returns_401():
    import asyncio

    async def scenario():
        client, sink = await _build_client({})

        body = _push_body()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=wrong",
                "X-GitHub-Delivery": "d1",
                "X-GitHub-Event": "push",
            },
        )

        assert response.status_code == 401
        assert sink.received == []

    asyncio.run(scenario())


def test_unregistered_repository_returns_ok_with_zero_mounts():
    import asyncio

    async def scenario():
        client, sink = await _build_client({}, register_repo=False)

        body = _push_body()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": _sign(body),
                "X-GitHub-Delivery": "d1",
                "X-GitHub-Event": "push",
            },
        )

        assert response.status_code == 200
        assert response.json()["mounts_processed"] == 0
        assert sink.received == []

    asyncio.run(scenario())


def test_missing_repository_info_returns_400():
    import asyncio

    async def scenario():
        client, sink = await _build_client({})

        body = json.dumps({"ref": "refs/heads/main", "commits": []}).encode("utf-8")
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": _sign(body),
                "X-GitHub-Delivery": "d1",
                "X-GitHub-Event": "push",
            },
        )

        assert response.status_code == 400

    asyncio.run(scenario())
