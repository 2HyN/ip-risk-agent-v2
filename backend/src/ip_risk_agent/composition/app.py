"""FastAPI assembly for the public API and internal analysis worker."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from .container import RuntimeContainer
from .health import create_health_router
from .pipeline import (
    InvalidPipelineTaskError,
    PipelineDisposition,
    RetryablePipelineError,
)
from .settings import AppRole


class AnalyzeChangeTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_event_id: str = Field(min_length=1, max_length=256)


class AnalyzeChangeTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disposition: PipelineDisposition
    change_event_id: str
    analysis_job_id: str | None = None
    terminal_job_status: str | None = None
    safe_code: str | None = None


def create_api_app(container: RuntimeContainer) -> FastAPI:
    if container.settings.role is not AppRole.API or container.control_api is None:
        raise ValueError("API app requires an API runtime container")
    app = FastAPI(title="IP Risk Agent API", lifespan=_lifespan(container))
    container.control_api.install(app)
    for router in container.source_routers.web:
        app.include_router(router)
    for router in container.source_routers.webhooks:
        app.include_router(router)
    for router in container.source_routers.desktop:
        app.include_router(router)
    if container.original_router is not None:
        app.include_router(container.original_router)
    for router in container.extra_api_routers:
        app.include_router(router)
    app.include_router(create_health_router(container.health))
    return app


def create_worker_app(container: RuntimeContainer) -> FastAPI:
    if container.settings.role is not AppRole.WORKER:
        raise ValueError("worker app requires a worker runtime container")
    app = FastAPI(title="IP Risk Agent Analysis Worker", lifespan=_lifespan(container))

    @app.post(
        "/internal/tasks/analyze-change",
        response_model=AnalyzeChangeTaskResponse,
    )
    async def analyze_change(
        body: AnalyzeChangeTask,
        request: Request,
    ) -> AnalyzeChangeTaskResponse:
        await container.task_authenticator(request)
        if container.pipeline is None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=503,
                detail={
                    "code": "CONFIGURATION:ANALYSIS_PIPELINE_MISSING",
                    "retryable": True,
                },
            )
        else:
            try:
                result = await container.pipeline.execute(
                    body.change_event_id,
                    allow_retry=True,
                )
            except RetryablePipelineError as exc:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=503,
                    detail={"code": exc.safe_code, "retryable": True},
                ) from exc
            except InvalidPipelineTaskError as exc:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="unknown change event") from exc
        return AnalyzeChangeTaskResponse(
            disposition=result.disposition,
            change_event_id=result.change_event_id,
            analysis_job_id=result.analysis_job_id,
            terminal_job_status=result.terminal_job_status,
            safe_code=result.safe_code,
        )

    app.include_router(create_health_router(container.health))
    return app


def _lifespan(container: RuntimeContainer):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            await container.close()

    return lifespan


__all__ = [
    "AnalyzeChangeTask",
    "AnalyzeChangeTaskResponse",
    "create_api_app",
    "create_worker_app",
]
