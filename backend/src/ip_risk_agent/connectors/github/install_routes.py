from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.oauth_state import OAuthStateStore, generate_state
from .oauth import build_install_url


class GitHubConnectionCreationCallback(Protocol):
    """Control의 canonical SourceConnection 생성. installation_id는 비밀이
    아니라 그냥 식별자라서 credential_vault를 거칠 필요가 없다 (B-2와 동일
    판단)."""

    async def create_github_connection(
        self, request: Request, *, risk_workspace_id: str, installation_id: str
    ) -> str: ...


class GitHubInstallStartRequest(BaseModel):
    risk_workspace_id: str


class GitHubInstallStartResponse(BaseModel):
    authorize_url: str
    state: str


class GitHubInstallCallbackResponse(BaseModel):
    connection_id: str
    installation_id: str
    status: str


def create_github_install_router(
    *,
    app_slug: str,
    state_store: OAuthStateStore,
    connection_creation_callback: GitHubConnectionCreationCallback,
    authz_dependency: AuthzDependency = deny_all_authz,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/source-connections/github/install/start", response_model=GitHubInstallStartResponse
    )
    async def start(request: Request, body: GitHubInstallStartRequest) -> GitHubInstallStartResponse:
        await authz_dependency(request, body.risk_workspace_id)

        state = generate_state()
        await state_store.save(state, {"risk_workspace_id": body.risk_workspace_id})

        return GitHubInstallStartResponse(
            authorize_url=build_install_url(app_slug=app_slug, state=state), state=state
        )

    @router.get(
        "/api/v1/source-connections/github/install/callback", response_model=GitHubInstallCallbackResponse
    )
    async def callback(request: Request, installation_id: str, state: str) -> GitHubInstallCallbackResponse:
        context = await state_store.consume(state)
        if context is None:
            raise HTTPException(status_code=400, detail="invalid or expired oauth state")

        connection_id = await connection_creation_callback.create_github_connection(
            request,
            risk_workspace_id=context["risk_workspace_id"],
            installation_id=installation_id,
        )

        return GitHubInstallCallbackResponse(
            connection_id=connection_id, installation_id=installation_id, status="connected"
        )

    return router
