from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.common.authz import allow_all_authz
from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.github.connection_lookup import (
    GitHubConnectionContext,
    InMemoryGitHubConnectionInstallationLookup,
)
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


class FakeInitialChangeSync:
    def __init__(self) -> None:
        self.mount_ids = []

    async def initialize(self, *, mount_id: str) -> None:
        self.mount_ids.append(mount_id)


class FakeMountConnectionLookup:
    """mount -> 그 mount 를 만든 연결."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def resolve(self, mount_id: str) -> GitHubConnectionContext:
        try:
            connection_id = self._mapping[mount_id]
        except KeyError as exc:
            raise NotFoundError(
                provider="github", safe_message="unknown mount"
            ) from exc
        return GitHubConnectionContext(
            installation_id="inst-1", operational_connection_id=connection_id
        )


def _build_client(provider: FakeGitHubProvider | None = None, *, initial_change_sync=None):
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
        initial_change_sync=initial_change_sync,
        mount_connection_lookup=FakeMountConnectionLookup({"mount-1": "conn-1"}),
        connection_authz_dependency=allow_all_authz,
        workspace_authz_dependency=allow_all_authz,
        mount_authz_dependency=allow_all_authz,
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


def test_create_mount_publishes_initial_repository_changes_after_scope_save():
    async def scenario():
        sync = FakeInitialChangeSync()
        client, _, tracking_scope_store, _ = _build_client(
            initial_change_sync=sync
        )

        response = client.post(
            "/api/v1/source-connections/conn-1/github/mounts",
            json={"risk_workspace_id": "rw1", "owner": "acme", "repo": "widgets"},
        )

        assert response.status_code == 200
        assert await tracking_scope_store.load("server-mount-1") is not None
        assert sync.mount_ids == ["server-mount-1"]

    import asyncio

    asyncio.run(scenario())


# ------------------------------------------- 저장소를 하나 붙인 뒤 더 붙이기


def test_a_second_repository_can_be_mounted_without_going_back_to_github():
    """저장소를 하나 붙이고 나면 다음 것을 붙일 길이 없었다.

    연결 범위 라우트는 connection_id 를 요구하는데 화면에 남는 것은 mount 뿐이다.
    그래서 GitHub 설치 화면을 다시 거쳐야 했는데, GitHub 은 **저장소 선택이 바뀔
    때만** 되돌려 보내므로 그 길도 막혀 있었다. 저장소 세 개를 한 번에 설치에
    추가해도 앱에서는 하나밖에 붙일 수 없었다.
    """
    repos = [
        GitHubRepository(id=1, full_name="acme/widgets", owner="acme", name="widgets", private=False, default_branch="main"),
        GitHubRepository(id=2, full_name="acme/gadgets", owner="acme", name="gadgets", private=False, default_branch="main"),
    ]
    client, factory, _, callback = _build_client(FakeGitHubProvider(repos=repos))

    listed = client.get("/api/v1/source-mounts/mount-1/github/repositories")
    assert listed.status_code == 200
    assert [item["full_name"] for item in listed.json()["repositories"]] == [
        "acme/widgets",
        "acme/gadgets",
    ]

    created = client.post(
        "/api/v1/source-mounts/mount-1/github/mounts",
        json={"risk_workspace_id": "vws-1", "owner": "acme", "repo": "gadgets"},
    )
    assert created.status_code == 200
    # 화면은 mount 만 알지만, 붙는 것은 그 mount 를 만든 **연결**이다.
    assert callback.calls[-1]["connection_id"] == "conn-1"
    assert callback.calls[-1]["repo"] == "gadgets"


def test_an_unknown_mount_cannot_reach_a_connection():
    """mount 를 통해 연결을 되찾는 길이 열려 있으므로, 그 입구가 좁아야 한다."""
    client, _, _, callback = _build_client()

    listed = client.get("/api/v1/source-mounts/not-a-mount/github/repositories")
    created = client.post(
        "/api/v1/source-mounts/not-a-mount/github/mounts",
        json={"risk_workspace_id": "vws-1", "owner": "acme", "repo": "gadgets"},
    )

    assert listed.status_code == 404
    assert created.status_code == 404
    assert callback.calls == []
