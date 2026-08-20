"""Browser-safe runtime configuration; never includes provider credentials."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .settings import Settings


class DrivePickerRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    browser_api_key: str | None = None
    cloud_project_number: str | None = None


class FrontendRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drive_picker: DrivePickerRuntimeConfig


def create_frontend_runtime_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["runtime"])

    @router.get("/api/v1/runtime-config", response_model=FrontendRuntimeConfig)
    async def runtime_config() -> FrontendRuntimeConfig:
        return FrontendRuntimeConfig(
            drive_picker=DrivePickerRuntimeConfig(
                enabled=settings.drive_picker_enabled,
                browser_api_key=settings.google_picker_api_key,
                cloud_project_number=settings.google_cloud_project_number,
            )
        )

    return router


__all__ = ["FrontendRuntimeConfig", "create_frontend_runtime_router"]
