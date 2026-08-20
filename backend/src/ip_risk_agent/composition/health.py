"""Safe liveness/readiness state for API and worker apps."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    ready: bool
    detail_safe: str


class HealthRegistry:
    def __init__(self, checks: tuple[ReadinessCheck, ...]) -> None:
        self._checks = checks

    @property
    def ready(self) -> bool:
        return all(check.ready for check in self._checks)

    @property
    def checks(self) -> tuple[ReadinessCheck, ...]:
        return self._checks


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    checks: dict[str, str] = Field(default_factory=dict)


def create_health_router(registry: HealthRegistry) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health/live", response_model=HealthResponse)
    async def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/health/ready", response_model=HealthResponse)
    async def ready(response: Response) -> HealthResponse:
        if not registry.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="ready" if registry.ready else "not_ready",
            checks={check.name: check.detail_safe for check in registry.checks},
        )

    return router


__all__ = ["HealthRegistry", "ReadinessCheck", "create_health_router"]
