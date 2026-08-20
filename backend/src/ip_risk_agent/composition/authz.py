"""Source 라우터 authz 를 Control Plane RBAC 에 연결한다.

두 Plane 의 모양이 다르다.

    Agent 2 :  async def (request: Request, resource_id: str) -> None
    Agent 1 :  async def (*, actor_user_id, risk_workspace_id, action, mount_id=None,
                          provider_credential_owner_user_id=None) -> FacadeAuthorizationDecision

그래서 그대로 꽂히지 않는다. 이 모듈이 그 사이를 메운다.

`resource_id` 는 라우트마다 의미가 다르므로(Agent 2 authz.py 주석) 라우트별로
어떤 스코프인지 명시해 만들어 쓴다. 하나의 함수로 뭉뚱그리면 mount_id 를
risk_workspace_id 로 오해하는 사고가 난다.

기본값 `allow_all_authz` 를 그대로 두면 Source 라우터 전체가 무검사로 열린다
(Agent 2 인계문서 10-1). 이 모듈의 존재 이유가 그 상태를 없애는 것이다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import HTTPException, Request, status

from ip_risk_agent.api.common import SESSION_KEY
from ip_risk_agent.application.public_facade import (
    PublicVwsAction,
    SourceAuthorizationCallback,
)
from ip_risk_agent.application.repositories import RecordNotFoundError

AuthzCallable = Callable[[Request, str], Awaitable[None]]


class MountWorkspaceResolver(Protocol):
    """mount_id -> risk_workspace_id. facade.get_mount_ref 가 이 모양을 만족한다."""

    async def __call__(self, mount_id: str) -> object: ...


class ConnectionWorkspaceResolver(Protocol):
    """connection_id -> risk_workspace_id.

    Control 은 connection 을 workspace 로 직접 되짚는 공개 메서드를 두지 않았다.
    Integration 이 소유한 connection 레지스트리가 이 역할을 한다.
    """

    async def resolve_workspace(self, connection_id: str) -> str | None: ...


def current_user_id(request: Request) -> str:
    """세션에서 사용자 ID 를 꺼낸다. Agent 1 라우터와 동일한 규약을 쓴다."""
    try:
        session = request.session
    except (AssertionError, KeyError):  # SessionMiddleware 미설치
        session = None
    value = session.get(SESSION_KEY) if isinstance(session, dict) else None
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="application session is required",
        )
    user_id = value.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="application session is malformed",
        )
    return user_id


async def _decide(
    authorize: SourceAuthorizationCallback,
    *,
    actor_user_id: str,
    risk_workspace_id: str,
    action: PublicVwsAction,
    mount_id: str | None = None,
) -> None:
    try:
        decision = await authorize(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            action=action,
            mount_id=mount_id,
        )
    except RecordNotFoundError:
        # 존재 여부를 권한 없는 사용자에게 알려주지 않는다.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not authorized"
        ) from None
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason or "not authorized"
        )


def workspace_scoped(
    authorize: SourceAuthorizationCallback, action: PublicVwsAction
) -> AuthzCallable:
    """`resource_id` 가 risk_workspace_id 인 라우트용."""

    async def dependency(request: Request, resource_id: str) -> None:
        actor = current_user_id(request)
        if not resource_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="risk_workspace_id is required",
            )
        await _decide(
            authorize,
            actor_user_id=actor,
            risk_workspace_id=resource_id,
            action=action,
        )

    return dependency


def mount_scoped(
    authorize: SourceAuthorizationCallback,
    action: PublicVwsAction,
    mount_ref_resolver: Callable[[str], Awaitable[object]],
) -> AuthzCallable:
    """`resource_id` 가 mount_id 인 라우트용. mount -> workspace 를 먼저 되짚는다."""

    async def dependency(request: Request, resource_id: str) -> None:
        actor = current_user_id(request)
        if not resource_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="mount_id is required"
            )
        try:
            mount_ref = await mount_ref_resolver(resource_id)
        except RecordNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="not authorized"
            ) from None
        workspace_id = getattr(mount_ref, "risk_workspace_id", None)
        if not isinstance(workspace_id, str) or not workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="not authorized"
            )
        await _decide(
            authorize,
            actor_user_id=actor,
            risk_workspace_id=workspace_id,
            action=action,
            mount_id=resource_id,
        )

    return dependency


def connection_scoped(
    authorize: SourceAuthorizationCallback,
    action: PublicVwsAction,
    connections: ConnectionWorkspaceResolver,
) -> AuthzCallable:
    """`resource_id` 가 connection_id 인 라우트용."""

    async def dependency(request: Request, resource_id: str) -> None:
        actor = current_user_id(request)
        if not resource_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="connection_id is required",
            )
        workspace_id = await connections.resolve_workspace(resource_id)
        if not workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="not authorized"
            )
        await _decide(
            authorize,
            actor_user_id=actor,
            risk_workspace_id=workspace_id,
            action=action,
        )

    return dependency


def session_only() -> AuthzCallable:
    """VWS 스코프가 없는 라우트용(예: 데스크톱 기기 등록).

    로그인 여부만 확인한다. 사용자 단위 자원이라 VWS Role 판단 대상이 아니다.
    """

    async def dependency(request: Request, resource_id: str) -> None:
        current_user_id(request)

    return dependency


def path_scoped(routes: dict[str, AuthzCallable], default: AuthzCallable) -> AuthzCallable:
    """경로 접미사별로 다른 스코프를 적용한다.

    Agent 2 의 라우터 하나가 여러 라우트를 담는데 `resource_id` 의 의미가
    라우트마다 다르다(device 등록은 빈 문자열, mount 등록은 risk_workspace_id,
    staging/event 는 mount_id). 그런데 주입 지점은 `authz_dependency` 하나다.
    그래서 요청 경로로 갈라 각자 맞는 스코프를 태운다.

    하나로 뭉뚱그려 가장 느슨한 검사를 걸면 mount 등록이 VWS 멤버십 검사 없이
    통과한다. Control 이 뒤에서 한 번 더 막기는 하지만, 경계에서 막는 편이
    실패를 훨씬 일찍 드러낸다.
    """

    async def dependency(request: Request, resource_id: str) -> None:
        path = request.url.path
        for suffix, handler in routes.items():
            if path.endswith(suffix):
                await handler(request, resource_id)
                return
        await default(request, resource_id)

    return dependency



__all__ = [
    "current_user_id",
    "AuthzCallable",
    "ConnectionWorkspaceResolver",
    "connection_scoped",
    "mount_scoped",
    "path_scoped",
    "session_only",
    "workspace_scoped",
]
