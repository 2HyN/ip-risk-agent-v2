"""Identity-protected, bounded maintenance endpoints for Cloud Scheduler."""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .task_auth import TaskAuthenticator


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursor: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=100, ge=1, le=500)


class MaintenanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    processed: int = Field(ge=0)
    failed: int = Field(ge=0)
    next_cursor: str | None = None


class SchedulerOperations(Protocol):
    async def renew_drive_watches(self, cursor: str | None, limit: int) -> MaintenanceResult: ...
    async def reconcile_drive(self, cursor: str | None, limit: int) -> MaintenanceResult: ...
    async def cleanup_expired(self, cursor: str | None, limit: int) -> MaintenanceResult: ...
    async def refresh_source_health(self, cursor: str | None, limit: int) -> MaintenanceResult: ...


def create_scheduler_router(
    *,
    authenticator: TaskAuthenticator,
    operations: SchedulerOperations,
) -> APIRouter:
    router = APIRouter(prefix="/internal/scheduler", tags=["scheduler"])

    async def execute(request: Request, body: MaintenanceRequest, operation):
        await authenticator(request)
        return await operation(body.cursor, body.limit)

    @router.post("/drive-watch-renewal", response_model=MaintenanceResult)
    async def drive_watch(request: Request, body: MaintenanceRequest) -> MaintenanceResult:
        return await execute(request, body, operations.renew_drive_watches)

    @router.post("/drive-reconciliation", response_model=MaintenanceResult)
    async def drive_reconcile(request: Request, body: MaintenanceRequest) -> MaintenanceResult:
        return await execute(request, body, operations.reconcile_drive)

    @router.post("/expired-state-cleanup", response_model=MaintenanceResult)
    async def cleanup(request: Request, body: MaintenanceRequest) -> MaintenanceResult:
        return await execute(request, body, operations.cleanup_expired)

    @router.post("/source-health-refresh", response_model=MaintenanceResult)
    async def source_health(request: Request, body: MaintenanceRequest) -> MaintenanceResult:
        return await execute(request, body, operations.refresh_source_health)

    return router


__all__ = [
    "MaintenanceRequest",
    "MaintenanceResult",
    "SchedulerOperations",
    "create_scheduler_router",
]
