"""Pure ChangeEvent processing transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ip_risk_agent.core.common import DomainInvariantError, normalize_utc, require_non_empty

from .models import ChangeEvent, ChangeEventStatus


def claim_change_event(
    event: ChangeEvent,
    *,
    occurred_at: datetime,
    lease_expires_at: datetime,
) -> ChangeEvent:
    if event.status is not ChangeEventStatus.PENDING:
        raise DomainInvariantError("only a PENDING change event may be claimed")
    occurred_at = normalize_utc(occurred_at, "change_event_claim.occurred_at")
    lease_expires_at = normalize_utc(
        lease_expires_at,
        "change_event_claim.lease_expires_at",
    )
    if lease_expires_at <= occurred_at:
        raise DomainInvariantError("change event lease must expire after claim time")
    return replace(
        event,
        status=ChangeEventStatus.PROCESSING,
        attempts=event.attempts + 1,
        updated_at=occurred_at,
        lease_expires_at=lease_expires_at,
    )


def reclaim_change_event(
    event: ChangeEvent,
    *,
    occurred_at: datetime,
    lease_expires_at: datetime,
) -> ChangeEvent:
    if event.status not in {ChangeEventStatus.PROCESSING, ChangeEventStatus.FAILED}:
        raise DomainInvariantError("only a PROCESSING or FAILED change event may be reclaimed")
    occurred_at = normalize_utc(occurred_at, "change_event_reclaim.occurred_at")
    lease_expires_at = normalize_utc(
        lease_expires_at,
        "change_event_reclaim.lease_expires_at",
    )
    if event.status is ChangeEventStatus.PROCESSING and (
        event.lease_expires_at is None or event.lease_expires_at > occurred_at
    ):
        raise DomainInvariantError("an active change event lease cannot be reclaimed")
    if lease_expires_at <= occurred_at:
        raise DomainInvariantError("reclaimed change event lease must be bounded")
    return replace(
        event,
        status=ChangeEventStatus.PROCESSING,
        attempts=event.attempts + 1,
        updated_at=occurred_at,
        last_error_safe=None,
        lease_expires_at=lease_expires_at,
    )


def complete_change_event(event: ChangeEvent, *, occurred_at: datetime) -> ChangeEvent:
    if event.status is not ChangeEventStatus.PROCESSING:
        raise DomainInvariantError("only a PROCESSING change event may complete")
    return replace(
        event,
        status=ChangeEventStatus.DONE,
        updated_at=normalize_utc(occurred_at, "change_event_completion.occurred_at"),
        lease_expires_at=None,
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
        lease_expires_at=None,
    )


def reanalyze_change_event(event: ChangeEvent, *, occurred_at: datetime) -> ChangeEvent:
    """사용자가 변경 없이 다시 검사하도록 되돌린다.

    `requeue_change_event` 는 FAILED 만 허용한다. 재검사는 이미 끝난(DONE) 결과도
    다시 돌려야 하므로 별도 전이가 필요하다. 진행 중인 것은 되돌리지 않는다 —
    돌리면 실행 중인 worker 의 결과가 뒤늦게 도착해 새 시도를 덮는다.
    """
    if event.status in {ChangeEventStatus.PENDING, ChangeEventStatus.PROCESSING}:
        raise DomainInvariantError("analysis is already in flight")
    return replace(
        event,
        status=ChangeEventStatus.PENDING,
        last_error_safe=None,
        updated_at=normalize_utc(occurred_at, "change_event_reanalyze.occurred_at"),
        lease_expires_at=None,
    )


def requeue_change_event(event: ChangeEvent, *, occurred_at: datetime) -> ChangeEvent:
    if event.status is not ChangeEventStatus.FAILED:
        raise DomainInvariantError("only a FAILED change event may be requeued")
    return replace(
        event,
        status=ChangeEventStatus.PENDING,
        last_error_safe=None,
        updated_at=normalize_utc(occurred_at, "change_event_requeue.occurred_at"),
        lease_expires_at=None,
    )


__all__ = [
    "claim_change_event",
    "reanalyze_change_event",
    "complete_change_event",
    "fail_change_event",
    "reclaim_change_event",
    "requeue_change_event",
]
