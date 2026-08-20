"""Agent 2 Spec §3/§37: VWS membership/role 판단은 Agent 1이 제공하는
authz_dependency를 주입받아 쓴다 — Agent 2가 직접 Membership DB를 읽지
않는다. 모든 provider 라우터가 이 하나의 shape을 공유한다.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, Request


class AuthzDependency(Protocol):
    """resource_id는 라우트마다 의미가 다르다 (mount_id, risk_workspace_id 등).
    허용되면 조용히 반환, 아니면 스스로 HTTPException(401/403)을 던진다."""

    async def __call__(self, request: Request, resource_id: str) -> None: ...


async def allow_all_authz(request: Request, resource_id: str) -> None:
    """개발/테스트 전용 기본값 — 아무 것도 검사하지 않는다.
    프로덕션 배포 전 반드시 Agent 1의 실제 authz_dependency로 교체해야 한다."""
    return None


async def deny_all_authz(request: Request, resource_id: str) -> None:
    """Fail-closed router default used until composition injects scoped authz."""
    raise HTTPException(
        status_code=401,
        detail="source authorization is not configured",
    )


__all__ = ["AuthzDependency", "allow_all_authz", "deny_all_authz"]
