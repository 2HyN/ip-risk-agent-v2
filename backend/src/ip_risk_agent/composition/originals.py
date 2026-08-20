"""Authorized Open Original dispatch across Source adapters."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from iprisk_contracts import OriginalSourceLocator, OriginalSourceType, SourceType

from ip_risk_agent.api.common import CsrfGuard, CurrentPrincipal, StrictApiModel
from ip_risk_agent.application.public_facade import PublicVwsAction

from .providers import ProviderRegistryError, SourceAdapterRegistry


class OriginalSourceResponse(StrictApiModel):
    original_source_type: OriginalSourceType
    provider_url: str | None = None
    device_id: str | None = None
    source_artifact_id: str | None = None
    metadata_safe: dict[str, object]


class OriginalSourceService:
    def __init__(self, *, control_facade, adapters: SourceAdapterRegistry) -> None:
        self._control = control_facade
        self._adapters = adapters

    async def resolve(
        self,
        *,
        actor_user_id: str,
        risk_workspace_id: str,
        artifact_id: str,
    ) -> OriginalSourceLocator:
        original = await self._control.get_original_source_request(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            artifact_id=artifact_id,
        )
        decision = await self._control.authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            action=PublicVwsAction.MOUNT_SOURCE_OPERATION,
            mount_id=original.mount.mount_id,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail="provider authority is required")
        try:
            adapter = self._adapters.require(original.mount.source_type)
        except ProviderRegistryError as exc:
            raise HTTPException(status_code=503, detail="source adapter is unavailable") from exc
        locator = await adapter.resolve_original(original.artifact)
        _validate_locator(original.mount.source_type, locator)
        return locator


def create_original_source_router(
    *,
    service: OriginalSourceService,
    principal_resolver,
) -> APIRouter:
    router = APIRouter(tags=["sources"])
    csrf = CsrfGuard()

    @router.post(
        "/api/v1/workspaces/{vws_id}/artifacts/{artifact_id}/open-original",
        response_model=OriginalSourceResponse,
    )
    async def open_original(
        vws_id: str,
        artifact_id: str,
        principal: CurrentPrincipal = Depends(principal_resolver),
        _csrf: None = Depends(csrf),
    ) -> OriginalSourceResponse:
        locator = await service.resolve(
            actor_user_id=principal.user.id,
            risk_workspace_id=vws_id,
            artifact_id=artifact_id,
        )
        return OriginalSourceResponse.model_validate(locator, from_attributes=True)

    return router


def _validate_locator(source_type: SourceType, locator: OriginalSourceLocator) -> None:
    if source_type is SourceType.LOCAL:
        if (
            locator.original_source_type is not OriginalSourceType.LOCAL_DEVICE
            or locator.provider_url is not None
            or not locator.device_id
            or not locator.source_artifact_id
        ):
            raise HTTPException(status_code=502, detail="invalid local source locator")
        return
    expected_host = {
        SourceType.GOOGLE_DRIVE: "drive.google.com",
        SourceType.GITHUB: "github.com",
    }[source_type]
    parsed = urlsplit(locator.provider_url or "")
    if (
        locator.original_source_type is not OriginalSourceType.PROVIDER_URL
        or parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise HTTPException(status_code=502, detail="invalid provider source locator")


__all__ = [
    "OriginalSourceResponse",
    "OriginalSourceService",
    "create_original_source_router",
]
