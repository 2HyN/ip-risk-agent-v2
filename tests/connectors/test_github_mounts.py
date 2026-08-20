from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.github.connection_lookup import InMemoryGitHubConnectionInstallationLookup
from ip_risk_agent.connectors.github.models import GitHubRepository
from ip_risk_agent.connectors.github.mounts_routes import (
    GitHubMountCreationResponse,
    create_github_mounts_router,
)


class FakeGitHubProvider:
    def __init__(self, repos: list[GitHubRepository] | None = None, default_branch: str = "main") -> None:
        self._repos = repos or []
        self._default_branch = default_branch

    async def get_installation_token(self):
        raise NotImplementedError

    async def get_default_branch(self, owner: str, repo: str) -> str:
        return self._default_branch

    async def get_commit(self, owner, repo, sha):
        raise NotImplementedError

    async def get_file_content(self, owner, repo, path, ref):
        raise NotImplementedError

    async def list_installation_repositories(self) -> list[GitHubRepository]:
        return self._repos


class FakeGitHubProviderFactory:
    def __init__(self, provider: FakeGitHubProvider) -> None:
        self._provider = provider
        self.created_with: list[str] = []

    def create(self, installation_id: str) -> FakeGitHubProvider:
        self.created_with.append(installation_id)
        return self._provider


class FakeMountCreationCallback:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_github_mount(
        self, request: Request, *, connection_id, risk_workspace_id, owner, repo, tracked_branch
    ) -> GitHubMountCreationResponse:
        self.calls.append(
            {
                "connection_id": connection_id,
                "risk_workspace_id": risk_workspace_id,
                "owner": owner,
                "repo": repo,
                "tracked_branch": tracked_branch,
            }
        )
        return GitHubMountCreationResponse(server_mount_id="server-mount-1", source_workspace_id="sw-1")


def _build_client(provider: FakeGitHubProvider | None = None):
    factory = FakeGitHubProviderFactory(provider or FakeGitHubProvider())
    lookup = InMemoryGitHubConnectionInstallationLookup()
    lookup.register("conn-1", "inst-1")
    tracking_scope_store = InMemoryRuntimeStore()
    callback = FakeMountCreationCallback()

    router = create_github_mounts_router(
        provider_factory=factory,
        connection_installation_lookup=lookup,
        tracking_scope_store=tracking_scope_store,
        mount_creation_callback=callback,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    return client, factory, tracking_scope_store, callback


def test_list_repositories_returns_installation_repos():
    repos = [
        GitHubRepository(id=1, full_name="acme/widgets", owner="acme", name="widgets", private=True, default_branch="main"),
        GitHubRepository(id=2, full_name="acme/gadgets", owner="acme", name="gadgets", private=False, default_branch="develop"),
    ]
    client, factory, _, _ = _build_client(FakeGitHubProvider(repos=repos))

    response = client.get("/api/v1/source-connections/conn-1/github/repositories")

    assert response.status_code == 200
    body = response.json()
    assert len(body["repositories"]) == 2
    assert body["repositories"][0]["full_name"] == "acme/widgets"
    assert factory.created_with == ["inst-1"]


def test_list_repositories_unknown_connection_returns_404():
    client, _, _, _ = _build_client()

    response = client.get("/api/v1/source-connections/never-registered/github/repositories")

    assert response.status_code >= 400


def test_create_mount_uses_default_branch_when_not_specified():
    async def scenario():
        client, _, tracking_scope_store, callback = _build_client(
            FakeGitHubProvider(default_branch="develop")
        )

        response = client.post(
            "/api/v1/source-connections/conn-1/github/mounts",
            json={"risk_workspace_id": "rw1", "owner": "acme", "repo": "widgets"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["server_mount_id"] == "server-mount-1"
        assert callback.calls[0]["tracked_branch"] == "develop"

        scope = await tracking_scope_store.load("server-mount-1")
        assert scope.tracked_branch == "develop"
        assert scope.default_branch == "develop"

    import asyncio

    asyncio.run(scenario())


def test_create_mount_respects_explicit_tracked_branch():
    async def scenario():
        client, _, tracking_scope_store, callback = _build_client(
            FakeGitHubProvider(default_branch="main")
        )

        response = client.post(
            "/api/v1/source-connections/conn-1/github/mounts",
            json={
                "risk_workspace_id": "rw1",
                "owner": "acme",
                "repo": "widgets",
                "tracked_branch": "release-2.0",
                "include_patterns": ["src/**"],
            },
        )

        assert response.status_code == 200
        scope = await tracking_scope_store.load("server-mount-1")
        assert scope.tracked_branch == "release-2.0"
        assert scope.default_branch == "main"
        assert scope.include_patterns == ["src/**"]

    import asyncio

    asyncio.run(scenario())
