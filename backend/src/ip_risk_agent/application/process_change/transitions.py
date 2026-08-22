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


def requeue_change_event(
    event: ChangeEvent,
    *,
    occurred_at: datetime,
    allow_done: bool = False,
) -> ChangeEvent:
    """FAILED 이벤트를 다시 줄 세운다.

    ``allow_done`` 은 미결(INCONCLUSIVE) 실행의 재개용이다. DONE 이벤트라도
    그 결론이 권위가 없으면(내용을 읽지 못한 채 끝난 분석 등) 다시 돌릴 수
    있어야 한다. 진짜 성공(SUCCEEDED)을 되돌리지 않는 책임은 호출부가
    job 상태로 진다.
    """
    allowed = {ChangeEventStatus.FAILED}
    if allow_done:
        allowed.add(ChangeEventStatus.DONE)
    if event.status not in allowed:
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
