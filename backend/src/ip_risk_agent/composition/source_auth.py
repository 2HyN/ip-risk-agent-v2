"""Fail-closed Source web authorization adapters owned by Integration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fastapi import HTTPException, Request

from ip_risk_agent.api.common import (
    CsrfGuard,
    CsrfValidationError,
    CurrentPrincipal,
)
from ip_risk_agent.application.auth import AuthenticationError
from ip_risk_agent.application.public_facade import PublicVwsAction


class PrincipalResolver(Protocol):
    async def __call__(self, request: Request) -> CurrentPrincipal: ...


@dataclass(frozen=True, slots=True)
class ConnectionAccess:
    risk_workspace_id: str
    owner_user_id: str


class ConnectionAccessResolver(Protocol):
    async def resolve_connection_access(self, connection_id: str) -> ConnectionAccess: ...


class SourceResourceScope(StrEnum):
    WORKSPACE = "WORKSPACE"
    CONNECTION = "CONNECTION"
    MOUNT = "MOUNT"


class SessionSourceAuthorizer:
    """Authenticate session/version, enforce CSRF, then authorize exact scope."""

    def __init__(
        self,
        *,
        principal_resolver: PrincipalResolver,
        control_facade,
        scope: SourceResourceScope,
        connection_resolver: ConnectionAccessResolver | None = None,
        csrf_guard: CsrfGuard | None = None,
    ) -> None:
        if scope is SourceResourceScope.CONNECTION and connection_resolver is None:
            raise ValueError("connection scope requires a connection resolver")
        self._principal_resolver = principal_resolver
        self._control = control_facade
        self._scope = scope
        self._connections = connection_resolver
        self._csrf = csrf_guard or CsrfGuard()

    async def __call__(self, request: Request, resource_id: str) -> None:
        try:
            principal = await self._principal_resolver(request)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail="authentication required") from exc

        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            try:
                await self._csrf(
                    request,
                    x_csrf_token=request.headers.get("X-CSRF-Token"),
                )
            except CsrfValidationError as exc:
                raise HTTPException(status_code=403, detail="CSRF validation failed") from exc

        mount_id: str | None = None
        provider_owner: str | None = None
        if self._scope is SourceResourceScope.WORKSPACE:
            risk_workspace_id = resource_id
            action = PublicVwsAction.SOURCE_MOUNT
        elif self._scope is SourceResourceScope.CONNECTION:
            assert self._connections is not None
            access = await self._connections.resolve_connection_access(resource_id)
            risk_workspace_id = access.risk_workspace_id
            provider_owner = access.owner_user_id
            action = PublicVwsAction.SOURCE_MOUNT
            if provider_owner != principal.user.id:
                raise HTTPException(status_code=403, detail="connection owner mismatch")
        else:
            mount = await self._control.get_mount_ref(resource_id)
            risk_workspace_id = mount.risk_workspace_id
            mount_id = mount.mount_id
            action = PublicVwsAction.MOUNT_SOURCE_OPERATION

        decision = await self._control.authorize_vws_action(
            actor_user_id=principal.user.id,
            risk_workspace_id=risk_workspace_id,
            action=action,
            mount_id=mount_id,
            provider_credential_owner_user_id=provider_owner,
        )
        if not decision.allowed:
            status = 401 if decision.reason == "AUTHENTICATION_REQUIRED" else 403
            raise HTTPException(status_code=status, detail="source operation denied")


__all__ = [
    "ConnectionAccess",
    "ConnectionAccessResolver",
    "PrincipalResolver",
    "SessionSourceAuthorizer",
    "SourceResourceScope",
]
