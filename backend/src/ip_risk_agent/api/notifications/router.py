"""Target-scoped in-app notification routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ip_risk_agent.application.auth import AuthenticationService
from ip_risk_agent.application.history.safety import (
    HistorySafetyPolicy,
    sanitize_history_mapping,
)
from ip_risk_agent.application.notifications import NotificationService
from ip_risk_agent.core.notifications import (
    NotificationStatus,
    NotificationType,
)

from ..common import (
    CsrfGuard,
    CursorCodec,
    CurrentPrincipal,
    CurrentPrincipalDependency,
    StrictApiModel,
    paginate,
)


class NotificationResponse(StrictApiModel):
    id: str
    user_id: str
    risk_workspace_id: str
    notification_type: NotificationType
    status: NotificationStatus
    created_at: datetime
    read_at: datetime | None
    metadata_safe: dict[str, object]


class NotificationInboxResponse(StrictApiModel):
    items: list[NotificationResponse]
    unread_count: int
    next_cursor: str | None


class NotificationReadResponse(StrictApiModel):
    notification: NotificationResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class NotificationRouterDependencies:
    notifications: NotificationService
    authentication: AuthenticationService
    cursor_codec: CursorCodec


def create_notifications_router(deps: NotificationRouterDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
    current = CurrentPrincipalDependency(deps.authentication)
    csrf = CsrfGuard()

    @router.get("", response_model=NotificationInboxResponse)
    async def list_notifications(
        principal: CurrentPrincipal = Depends(current),
        unread_only: bool = False,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        inbox = await deps.notifications.list_for_user(
            actor_user_id=principal.user.id,
            unread_only=unread_only,
            limit=10_000,
        )
        selected, next_cursor = paginate(
            inbox.notifications,
            cursor=cursor,
            limit=limit,
            scope=f"notifications:{principal.user.id}:{unread_only}",
            codec=deps.cursor_codec,
        )
        return NotificationInboxResponse(
            items=[_notification_response(item) for item in selected],
            unread_count=inbox.unread_count,
            next_cursor=next_cursor,
        )

    @router.post("/{notification_id}/read", response_model=NotificationReadResponse)
    async def mark_read(
        notification_id: str,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        result = await deps.notifications.mark_read(
            actor_user_id=principal.user.id,
            notification_id=notification_id,
        )
        return NotificationReadResponse(
            notification=_notification_response(result.notification),
            changed=result.changed,
        )

    return router


def _notification_response(notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        user_id=notification.user_id,
        risk_workspace_id=notification.risk_workspace_id,
        notification_type=notification.notification_type,
        status=notification.status,
        created_at=notification.created_at,
        read_at=notification.read_at,
        metadata_safe=dict(
            sanitize_history_mapping(
                notification.metadata_safe,
                HistorySafetyPolicy(),
            )
        ),
    )


__all__ = ["NotificationRouterDependencies", "create_notifications_router"]
