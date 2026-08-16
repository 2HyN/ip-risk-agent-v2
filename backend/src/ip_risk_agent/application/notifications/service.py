"""Target-scoped in-app notification queries and idempotent read transition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from ip_risk_agent.application.repositories import (
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.common import normalize_utc
from ip_risk_agent.core.notifications import (
    Notification,
    NotificationStatus,
)

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class NotificationInbox:
    user_id: str
    notifications: tuple[Notification, ...]
    unread_count: int


@dataclass(frozen=True, slots=True)
class NotificationReadResult:
    notification: Notification
    changed: bool


class NotificationService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    async def list_for_user(
        self,
        *,
        actor_user_id: str,
        unread_only: bool = False,
        limit: int = 100,
    ) -> NotificationInbox:
        _require_limit(limit)
        async with self._unit_of_work_factory() as uow:
            await _require_user(uow, actor_user_id)
            all_notifications = await uow.notifications.list_for_user(actor_user_id)
        unread_count = sum(
            item.status is NotificationStatus.UNREAD for item in all_notifications
        )
        selected = (
            tuple(
                item
                for item in all_notifications
                if item.status is NotificationStatus.UNREAD
            )
            if unread_only
            else all_notifications
        )
        selected = tuple(
            sorted(
                selected,
                key=lambda item: (item.created_at, item.id),
                reverse=True,
            )[:limit]
        )
        return NotificationInbox(actor_user_id, selected, unread_count)

    async def mark_read(
        self,
        *,
        actor_user_id: str,
        notification_id: str,
    ) -> NotificationReadResult:
        async with self._unit_of_work_factory() as uow:
            await _require_user(uow, actor_user_id)
            notification = await uow.notifications.get(notification_id)
            if notification is None or notification.user_id != actor_user_id:
                raise RecordNotFoundError(
                    f"notification was not found: {notification_id!r}"
                )
            if notification.status is NotificationStatus.READ:
                return NotificationReadResult(notification, changed=False)
            read_at = max(
                normalize_utc(self._clock(), "notification_read.clock"),
                notification.created_at,
            )
            notification = replace(
                notification,
                status=NotificationStatus.READ,
                read_at=read_at,
            )
            await uow.notifications.save(notification)
            await uow.commit()
        return NotificationReadResult(notification, changed=True)


async def _require_user(uow: ControlUnitOfWork, user_id: str) -> None:
    if await uow.users.get(user_id) is None:
        raise RecordNotFoundError(f"user was not found: {user_id!r}")


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or limit < 1 or limit > 10_000:
        raise ValueError("notification limit must be between 1 and 10000")


__all__ = [
    "NotificationInbox",
    "NotificationReadResult",
    "NotificationService",
]
