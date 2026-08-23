"""Workspace activity, audit, source-access, and safe export routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Awaitable, Callable

from fastapi import APIRouter, Depends, Query

from ip_risk_agent.application.auth import AuthenticationService
from ip_risk_agent.application.history import HistoryQueryService, WorkspaceActivity

from ..common import (
    CursorCodec,
    CurrentPrincipal,
    CurrentPrincipalDependency,
    Page,
    StrictApiModel,
    paginate,
)
from .models import HistoryEntryResponse


class HistoryExportResponse(StrictApiModel):
    risk_workspace_id: str
    generated_at: datetime
    entries: list[HistoryEntryResponse]


@dataclass(frozen=True, slots=True)
class HistoryRouterDependencies:
    history: HistoryQueryService
    authentication: AuthenticationService
    cursor_codec: CursorCodec


def create_history_router(deps: HistoryRouterDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/v1/workspaces/{vws_id}", tags=["history"])
    current = CurrentPrincipalDependency(deps.authentication)

    async def _page(
        *,
        loader: Callable[..., Awaitable[WorkspaceActivity]],
        vws_id: str,
        actor_user_id: str,
        cursor: str | None,
        limit: int,
        scope_name: str,
    ) -> Page[HistoryEntryResponse]:
        activity = await loader(
            risk_workspace_id=vws_id,
            actor_user_id=actor_user_id,
            limit=10_000,
        )
        selected, next_cursor = paginate(
            activity.entries,
            cursor=cursor,
            limit=limit,
            scope=f"{scope_name}:{vws_id}",
            codec=deps.cursor_codec,
        )
        return Page(
            items=[HistoryEntryResponse.from_entry(item) for item in selected],
            next_cursor=next_cursor,
        )

    @router.get("/activity", response_model=Page[HistoryEntryResponse])
    async def activity(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        return await _page(
            loader=deps.history.list_workspace_activity,
            vws_id=vws_id,
            actor_user_id=principal.user.id,
            cursor=cursor,
            limit=limit,
            scope_name="activity",
        )

    @router.get("/risk-events", response_model=Page[HistoryEntryResponse])
    async def risk_events(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        """Risk 생애 사건만 — 전체 활동에서는 접근 기록에 묻힌다."""
        return await _page(
            loader=deps.history.list_risk_events,
            vws_id=vws_id,
            actor_user_id=principal.user.id,
            cursor=cursor,
            limit=limit,
            scope_name="risk-events",
        )

    @router.get("/audit", response_model=Page[HistoryEntryResponse])
    async def audit(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        return await _page(
            loader=deps.history.list_audit_events,
            vws_id=vws_id,
            actor_user_id=principal.user.id,
            cursor=cursor,
            limit=limit,
            scope_name="audit",
        )

    @router.get("/source-access", response_model=Page[HistoryEntryResponse])
    async def source_access(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        return await _page(
            loader=deps.history.list_source_access_events,
            vws_id=vws_id,
            actor_user_id=principal.user.id,
            cursor=cursor,
            limit=limit,
            scope_name="source-access",
        )

    @router.get("/audit/export", response_model=HistoryExportResponse)
    async def export_history(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        limit: Annotated[int, Query(ge=1, le=500)] = 500,
    ):
        exported = await deps.history.export_workspace_history(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            limit=limit,
        )
        return HistoryExportResponse.model_validate(exported.to_safe_dict())

    return router


__all__ = ["HistoryRouterDependencies", "create_history_router"]
