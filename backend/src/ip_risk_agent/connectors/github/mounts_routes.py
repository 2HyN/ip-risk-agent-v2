from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.errors import NotFoundError, SourceConnectorError
from .connection_lookup import (
    GitHubConnectionInstallationLookup,
    GitHubConnectionLookup,
)
from .models import GitHubProvider
from .tracking_scope import GitHubTrackingScope


class GitHubProviderFactory(Protocol):
    def create(self, installation_id: str) -> GitHubProvider: ...


class GitHubRepositoryResponse(BaseModel):
    id: int
    full_name: str
    owner: str
    name: str
    private: bool
    default_branch: str


class GitHubRepositoriesListResponse(BaseModel):
    repositories: list[GitHubRepositoryResponse]


class GitHubMountCreationRequest(BaseModel):
    risk_workspace_id: str
    owner: str
    repo: str
    tracked_branch: str | None = None
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []


class GitHubMountCreationResponse(BaseModel):
    server_mount_id: str
    source_workspace_id: str


class GitHubMountCreationCallback(Protocol):
    """Control의 canonical SourceWorkspace/Mount 생성."""

    async def create_github_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        owner: str,
        repo: str,
        tracked_branch: str,
    ) -> GitHubMountCreationResponse: ...


class GitHubInitialChangeSync(Protocol):
    async def initialize(self, *, mount_id: str) -> None: ...


def create_github_mounts_router(
    *,
    provider_factory: GitHubProviderFactory,
    connection_installation_lookup: GitHubConnectionInstallationLookup,
    tracking_scope_store,
    mount_creation_callback: GitHubMountCreationCallback,
    initial_change_sync: GitHubInitialChangeSync | None = None,
    mount_connection_lookup: GitHubConnectionLookup | None = None,
    connection_authz_dependency: AuthzDependency = deny_all_authz,
    workspace_authz_dependency: AuthzDependency = deny_all_authz,
    mount_authz_dependency: AuthzDependency = deny_all_authz,
) -> APIRouter:
    router = APIRouter()

    async def _connection_for_mount(request: Request, mount_id: str) -> str:
        """이미 붙어 있는 mount 로부터 그 연결을 찾는다.

        저장소를 하나 붙이고 나면 화면에는 mount 만 남는다. 연결 식별자를 화면에
        내보내면 같은 계정의 여러 workspace 경계가 흐려지므로, Drive 와 같은
        방식으로 **mount 인가를 거쳐** 연결을 되찾는다.
        """
        await mount_authz_dependency(request, mount_id)
        if mount_connection_lookup is None:
            raise HTTPException(status_code=404, detail="unknown GitHub mount")
        try:
            context = await mount_connection_lookup.resolve(mount_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown GitHub mount") from exc
        if context.operational_connection_id is None:
            raise HTTPException(status_code=404, detail="unknown GitHub mount")
        return context.operational_connection_id

    @router.get(
        "/api/v1/source-connections/{connection_id}/github/repositories",
        response_model=GitHubRepositoriesListResponse,
    )
    async def list_repositories(connection_id: str, request: Request) -> GitHubRepositoriesListResponse:
        await connection_authz_dependency(request, connection_id)
        return await _repositories(connection_id)

    async def _repositories(connection_id: str) -> GitHubRepositoriesListResponse:
        try:
            installation_id = await connection_installation_lookup.resolve_installation_id(connection_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown source connection") from exc
        provider = provider_factory.create(installation_id)
        repos = await provider.list_installation_repositories()

        return GitHubRepositoriesListResponse(
            repositories=[
                GitHubRepositoryResponse(
                    id=r.id,
                    full_name=r.full_name,
                    owner=r.owner,
                    name=r.name,
                    private=r.private,
                    default_branch=r.default_branch,
                )
                for r in repos
            ]
        )

    @router.post(
        "/api/v1/source-connections/{connection_id}/github/mounts",
        response_model=GitHubMountCreationResponse,
    )
    async def create_mount(
        connection_id: str, request: Request, body: GitHubMountCreationRequest
    ) -> GitHubMountCreationResponse:
        await connection_authz_dependency(request, connection_id)
        await workspace_authz_dependency(request, body.risk_workspace_id)
        return await _mount(request, connection_id, body)

    async def _mount(
        request: Request, connection_id: str, body: GitHubMountCreationRequest
    ) -> GitHubMountCreationResponse:
        try:
            installation_id = await connection_installation_lookup.resolve_installation_id(connection_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="unknown source connection") from exc
        provider = provider_factory.create(installation_id)

        default_branch = await provider.get_default_branch(body.owner, body.repo)
        tracked_branch = body.tracked_branch or default_branch

        result = await mount_creation_callback.create_github_mount(
            request,
            connection_id=connection_id,
            risk_workspace_id=body.risk_workspace_id,
            owner=body.owner,
            repo=body.repo,
            tracked_branch=tracked_branch,
        )

        await tracking_scope_store.save(
            result.server_mount_id,
            GitHubTrackingScope(
                mount_id=result.server_mount_id,
                owner=body.owner,
                repo=body.repo,
                default_branch=default_branch,
                tracked_branch=tracked_branch,
                include_patterns=body.include_patterns,
                exclude_patterns=body.exclude_patterns,
            ),
        )

        if initial_change_sync is not None:
            try:
                await initial_change_sync.initialize(
                    mount_id=result.server_mount_id,
                )
            except SourceConnectorError as exc:
                raise HTTPException(
                    status_code=503 if exc.retryable else 502,
                    detail={
                        "code": "GITHUB_INITIAL_SYNC_FAILED",
                        "operation": "github_repository_tree",
                        "provider_error": exc.category.value,
                        "retryable": exc.retryable,
                    },
                ) from exc

        return result

    # ── 이미 붙어 있는 mount 를 통해 **같은 연결에 저장소를 더 붙인다.**
    #
    # 예전에는 저장소를 하나 붙이고 나면 다음 것을 붙일 길이 없었다. 연결 범위
    # 라우트는 connection_id 를 요구하는데 화면에는 mount 만 남기 때문이다. 그래서
    # GitHub 설치 화면을 다시 거쳐야 했는데, GitHub 은 **저장소 선택이 바뀔 때만**
    # 되돌려 보내므로 그 길도 막혀 있었다.

    @router.get(
        "/api/v1/source-mounts/{mount_id}/github/repositories",
        response_model=GitHubRepositoriesListResponse,
    )
    async def list_repositories_for_mount(
        mount_id: str, request: Request
    ) -> GitHubRepositoriesListResponse:
        connection_id = await _connection_for_mount(request, mount_id)
        return await _repositories(connection_id)

    @router.post(
        "/api/v1/source-mounts/{mount_id}/github/mounts",
        response_model=GitHubMountCreationResponse,
    )
    async def create_additional_mount(
        mount_id: str, request: Request, body: GitHubMountCreationRequest
    ) -> GitHubMountCreationResponse:
        connection_id = await _connection_for_mount(request, mount_id)
        await workspace_authz_dependency(request, body.risk_workspace_id)
        return await _mount(request, connection_id, body)

    return router
