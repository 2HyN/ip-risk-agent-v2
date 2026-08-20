"""Callback protocols that Integration may inject into Source-owned routers."""

from __future__ import annotations

from typing import Protocol

from .models import (
    FacadeAuthorizationDecision,
    PublicVwsAction,
    SourceMetadataRegistration,
    SourceMetadataRegistrationCommand,
)


class SourceAuthorizationCallback(Protocol):
    async def __call__(
        self,
        *,
        actor_user_id: str,
        risk_workspace_id: str,
        action: PublicVwsAction,
        mount_id: str | None = None,
        provider_credential_owner_user_id: str | None = None,
    ) -> FacadeAuthorizationDecision: ...


class SourceMetadataRegistrationCallback(Protocol):
    async def __call__(
        self,
        command: SourceMetadataRegistrationCommand,
    ) -> SourceMetadataRegistration: ...


__all__ = ["SourceAuthorizationCallback", "SourceMetadataRegistrationCallback"]
