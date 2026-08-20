"""Pure ChangeEvent processing transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ip_risk_agent.core.common import DomainInvariantError, normalize_utc, require_non_empty

from .models import ChangeEvent, ChangeEventStatus


def claim_change_event(event: ChangeEvent, *, occurred_at: datetime) -> ChangeEvent:
    if event.status is not ChangeEventStatus.PENDING:
        raise DomainInvariantError("only a PENDING change event may be claimed")
    occurred_at = normalize_utc(occurred_at, "change_event_claim.occurred_at")
    return replace(
        event,
        status=ChangeEventStatus.PROCESSING,
        attempts=event.attempts + 1,
        updated_at=occurred_at,
    )


def complete_change_event(event: ChangeEvent, *, occurred_at: datetime) -> ChangeEvent:
    if event.status is not ChangeEventStatus.PROCESSING:
        raise DomainInvariantError("only a PROCESSING change event may complete")
    return replace(
        event,
        status=ChangeEventStatus.DONE,
        updated_at=normalize_utc(occurred_at, "change_event_completion.occurred_at"),
    )


def fail_change_event(
    event: ChangeEvent,
    *,
    occurred_at: datetime,
    failure_safe: str,
) -> ChangeEvent:
    if event.status is not ChangeEventStatus.PROCESSING:
        raise DomainInvariantError("only a PROCESSING change event may fail")
    return replace(
        event,
        status=ChangeEventStatus.FAILED,
        last_error_safe=require_non_empty(failure_safe, "change_event.failure_safe"),
        updated_at=normalize_utc(occurred_at, "change_event_failure.occurred_at"),
    )


def requeue_change_event(event: ChangeEvent, *, occurred_at: datetime) -> ChangeEvent:
    if event.status is not ChangeEventStatus.FAILED:
        raise DomainInvariantError("only a FAILED change event may be requeued")
    return replace(
        event,
        status=ChangeEventStatus.PENDING,
        last_error_safe=None,
        updated_at=normalize_utc(occurred_at, "change_event_requeue.occurred_at"),
    )


__all__ = [
    "claim_change_event",
    "complete_change_event",
    "fail_change_event",
    "requeue_change_event",
]
