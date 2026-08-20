from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.errors import NotFoundError
from .connection_lookup import GitHubConnectionInstallationLookup
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


def create_github_mounts_router(
    *,
    provider_factory: GitHubProviderFactory,
    connection_installation_lookup: GitHubConnectionInstallationLookup,
    tracking_scope_store,
    mount_creation_callback: GitHubMountCreationCallback,
    connection_authz_dependency: AuthzDependency = deny_all_authz,
    workspace_authz_dependency: AuthzDependency = deny_all_authz,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/source-connections/{connection_id}/github/repositories",
        response_model=GitHubRepositoriesListResponse,
    )
    async def list_repositories(connection_id: str, request: Request) -> GitHubRepositoriesListResponse:
        await connection_authz_dependency(request, connection_id)

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

        return result

    return router
