"""Transactional human review updates, independent from machine lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from ip_risk_agent.application.history.safety import (
    HistorySafetyPolicy,
    sanitize_optional_history_text,
)
from ip_risk_agent.application.repositories import (
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.common import ActorType, DomainInvariantError, normalize_utc
from ip_risk_agent.core.memberships import (
    VwsAction,
    authorize_vws_action,
    require_authorized,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    decide_user_review,
    risk_review_event_id_for,
)

Clock = Callable[[], datetime]


class RiskReviewDisposition(StrEnum):
    APPLIED = "APPLIED"
    UNCHANGED = "UNCHANGED"


class RiskReviewConflictError(DomainInvariantError):
    def __init__(self, *, expected_version: int, current_version: int) -> None:
        super().__init__(
            "risk review version conflict: "
            f"expected {expected_version}, current {current_version}"
        )
        self.expected_version = expected_version
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class RiskReviewResult:
    disposition: RiskReviewDisposition
    risk: Risk
    event: RiskEvent | None


class RiskReviewService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
        safety_policy: HistorySafetyPolicy | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._safety = safety_policy or HistorySafetyPolicy()

    async def change_disposition(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        risk_id: str,
        expected_review_version: int,
        new_disposition: ReviewDisposition,
        comment: str | None = None,
    ) -> RiskReviewResult:
        if isinstance(expected_review_version, bool) or expected_review_version < 0:
            raise ValueError("expected_review_version cannot be negative")
        if not isinstance(new_disposition, ReviewDisposition):
            raise ValueError("new_disposition must be a ReviewDisposition")
        async with self._unit_of_work_factory() as uow:
            if await uow.workspaces.get(risk_workspace_id) is None:
                raise RecordNotFoundError(
                    f"workspace was not found: {risk_workspace_id!r}"
                )
            membership = await uow.memberships.get(
                risk_workspace_id,
                actor_user_id,
            )
            require_authorized(
                authorize_vws_action(
                    actor_user_id=actor_user_id,
                    risk_workspace_id=risk_workspace_id,
                    membership=membership,
                    action=VwsAction.RISK_REVIEW,
                )
            )
            risk = await uow.risks.get(risk_id)
            if risk is None or risk.risk_workspace_id != risk_workspace_id:
                raise RecordNotFoundError(f"risk was not found: {risk_id!r}")
            if risk.review_version != expected_review_version:
                raise RiskReviewConflictError(
                    expected_version=expected_review_version,
                    current_version=risk.review_version,
                )
            decision = decide_user_review(risk.review_disposition, new_disposition)
            if not decision.changed:
                return RiskReviewResult(
                    disposition=RiskReviewDisposition.UNCHANGED,
                    risk=risk,
                    event=None,
                )

            occurred_at = max(
                normalize_utc(self._clock(), "risk_review.clock"),
                risk.updated_at,
            )
            next_version = risk.review_version + 1
            updated = replace(
                risk,
                review_disposition=new_disposition,
                review_version=next_version,
                updated_at=occurred_at,
            )
            event = RiskEvent(
                id=risk_review_event_id_for(risk.id, next_version),
                risk_id=risk.id,
                event_type=RiskEventType.REVIEW_DISPOSITION_CHANGED,
                actor_type=ActorType.USER,
                actor_user_id=actor_user_id,
                occurred_at=occurred_at,
                previous_state_safe={
                    "review_disposition": risk.review_disposition.value,
                    "review_version": risk.review_version,
                },
                new_state_safe={
                    "review_disposition": updated.review_disposition.value,
                    "review_version": updated.review_version,
                },
                reason_safe=sanitize_optional_history_text(comment, self._safety),
            )
            await uow.risks.save(updated)
            await uow.risks.append_event(event)
            await uow.commit()
        return RiskReviewResult(RiskReviewDisposition.APPLIED, updated, event)


__all__ = [
    "RiskReviewConflictError",
    "RiskReviewDisposition",
    "RiskReviewResult",
    "RiskReviewService",
]
