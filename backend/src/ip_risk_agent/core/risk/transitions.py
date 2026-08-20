"""Pure Risk lifecycle and review decision functions."""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts import AnalysisCoverage, AnalysisStatus

from .models import ReviewDisposition, RiskEventType, RiskLifecycleState


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    previous_state: RiskLifecycleState | None
    next_state: RiskLifecycleState | None
    event_type: RiskEventType | None
    authoritative: bool

    @property
    def changed(self) -> bool:
        return self.previous_state is not self.next_state


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    previous_disposition: ReviewDisposition
    next_disposition: ReviewDisposition
    event_type: RiskEventType | None

    @property
    def changed(self) -> bool:
        return self.previous_disposition is not self.next_disposition


def analysis_is_authoritative(status: AnalysisStatus, coverage: AnalysisCoverage) -> bool:
    return status is AnalysisStatus.SUCCEEDED and coverage is AnalysisCoverage.COMPLETE


def decide_lifecycle(
    previous_state: RiskLifecycleState | None,
    *,
    candidate_present: bool,
    status: AnalysisStatus,
    coverage: AnalysisCoverage,
) -> LifecycleDecision:
    """Decide lifecycle without allowing incomplete analysis to change Risk truth."""

    authoritative = analysis_is_authoritative(status, coverage)
    if not authoritative:
        return LifecycleDecision(previous_state, previous_state, None, False)

    if candidate_present:
        if previous_state is None:
            return LifecycleDecision(None, RiskLifecycleState.NEW, RiskEventType.DETECTED, True)
        if previous_state is RiskLifecycleState.RESOLVED:
            return LifecycleDecision(
                previous_state,
                RiskLifecycleState.EXISTING,
                RiskEventType.REOPENED,
                True,
            )
        return LifecycleDecision(
            previous_state,
            RiskLifecycleState.EXISTING,
            RiskEventType.CONFIRMED,
            True,
        )

    if previous_state in {RiskLifecycleState.NEW, RiskLifecycleState.EXISTING}:
        return LifecycleDecision(
            previous_state,
            RiskLifecycleState.RESOLVED,
            RiskEventType.RESOLVED,
            True,
        )
    return LifecycleDecision(previous_state, previous_state, None, True)


def decide_review(
    previous_disposition: ReviewDisposition,
    next_disposition: ReviewDisposition,
) -> ReviewDecision:
    """Change human review independently from the machine lifecycle."""

    event_type = (
        RiskEventType.REVIEW_DISPOSITION_CHANGED
        if previous_disposition is not next_disposition
        else None
    )
    return ReviewDecision(previous_disposition, next_disposition, event_type)
