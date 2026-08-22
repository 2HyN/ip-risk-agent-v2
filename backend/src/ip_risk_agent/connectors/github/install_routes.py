from __future__ import annotations

from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from iprisk_contracts import SourceType
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
    completion_redirect: Callable[..., str] | None = None,
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
    async def callback(request: Request, installation_id: str, state: str) -> Response:
        context = await state_store.consume(state)
        if context is None:
        # state 는 일회용이고 수명이 짧다. 승인 화면을 오래 붙들거나 **뒤로가기로
        # 옛 URL 을 다시 열면** 여기로 온다. 무엇을 다시 해야 하는지 말해 주지
        # 않으면 사용자는 같은 실패를 반복한다 — 이번 GitHub 연결에서 소비되지 않은
        # state 가 4 개 쌓였다.
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "OAUTH_STATE_EXPIRED",
                    "message": (
                        "연결 요청이 만료되었거나 이미 사용되었습니다. "
                        "앱의 Sources 화면에서 연결을 다시 시작해 주세요."
                    ),
                },
            )

        connection_id = await connection_creation_callback.create_github_connection(
            request,
            risk_workspace_id=context["risk_workspace_id"],
            installation_id=installation_id,
        )

        result = GitHubInstallCallbackResponse(
            connection_id=connection_id, installation_id=installation_id, status="connected"
        )
        if completion_redirect is not None:
            return RedirectResponse(
                completion_redirect(
                    source_type=SourceType.GITHUB,
                    risk_workspace_id=context["risk_workspace_id"],
                    connection_id=connection_id,
                ),
                status_code=303,
            )
        return JSONResponse(result.model_dump())

    return router
