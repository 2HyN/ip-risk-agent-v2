"""Browser-safe runtime configuration; never includes provider credentials."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .settings import Settings


class DriveSharingRuntimeConfig(BaseModel):
    """D1 — 화면이 알아야 할 것은 **어디로 공유하는가** 하나뿐이다.

    Picker 설정을 대신한다. Picker 는 브라우저 API 키를 내려보내야 했는데, 그 키로
    할 수 있는 일이 있었다. 공유 주소는 그렇지 않다 — 알아도 접근이 생기지 않는다.
    접근은 사용자가 폴더를 공유해야만 생긴다.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool
    sharing_address: str | None = None


class FrontendRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drive_sharing: DriveSharingRuntimeConfig


def create_frontend_runtime_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["runtime"])

    @router.get("/api/v1/runtime-config", response_model=FrontendRuntimeConfig)
    async def runtime_config() -> FrontendRuntimeConfig:
        return FrontendRuntimeConfig(
            drive_sharing=DriveSharingRuntimeConfig(
                enabled=settings.drive_enabled,
                sharing_address=settings.drive_service_account,
            )
        )

    return router


__all__ = ["FrontendRuntimeConfig", "create_frontend_runtime_router"]
