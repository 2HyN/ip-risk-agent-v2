from __future__ import annotations

import pytest

from iprisk_contracts import AnalysisCoverage, AnalysisStatus
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    RiskEventType,
    RiskLifecycleState,
    analysis_is_authoritative,
    decide_lifecycle,
    decide_review,
)


def test_only_succeeded_complete_analysis_is_authoritative() -> None:
    assert analysis_is_authoritative(AnalysisStatus.SUCCEEDED, AnalysisCoverage.COMPLETE)
    for status, coverage in (
        (AnalysisStatus.SUCCEEDED, AnalysisCoverage.PARTIAL),
        (AnalysisStatus.SUCCEEDED, AnalysisCoverage.NONE),
        (AnalysisStatus.FAILED, AnalysisCoverage.NONE),
        (AnalysisStatus.INCONCLUSIVE, AnalysisCoverage.NONE),
        (AnalysisStatus.SKIPPED, AnalysisCoverage.NONE),
    ):
        assert not analysis_is_authoritative(status, coverage)


@pytest.mark.parametrize(
    ("status", "coverage"),
    [
        (AnalysisStatus.SUCCEEDED, AnalysisCoverage.PARTIAL),
        (AnalysisStatus.SUCCEEDED, AnalysisCoverage.NONE),
        (AnalysisStatus.FAILED, AnalysisCoverage.NONE),
        (AnalysisStatus.INCONCLUSIVE, AnalysisCoverage.NONE),
        (AnalysisStatus.SKIPPED, AnalysisCoverage.NONE),
    ],
)
def test_incomplete_or_failed_analysis_preserves_active_risk(status, coverage) -> None:
    decision = decide_lifecycle(
        RiskLifecycleState.EXISTING,
        candidate_present=False,
        status=status,
        coverage=coverage,
    )
    assert decision.next_state is RiskLifecycleState.EXISTING
    assert decision.event_type is None
    assert not decision.authoritative


def test_incomplete_analysis_cannot_create_a_new_risk() -> None:
    decision = decide_lifecycle(
        None,
        candidate_present=True,
        status=AnalysisStatus.SUCCEEDED,
        coverage=AnalysisCoverage.PARTIAL,
    )
    assert decision.next_state is None
    assert decision.event_type is None


def test_complete_analysis_detects_confirms_resolves_and_reopens() -> None:
    detected = decide_lifecycle(
        None,
        candidate_present=True,
        status=AnalysisStatus.SUCCEEDED,
        coverage=AnalysisCoverage.COMPLETE,
    )
    confirmed = decide_lifecycle(
        RiskLifecycleState.NEW,
        candidate_present=True,
        status=AnalysisStatus.SUCCEEDED,
        coverage=AnalysisCoverage.COMPLETE,
    )
    resolved = decide_lifecycle(
        RiskLifecycleState.EXISTING,
        candidate_present=False,
        status=AnalysisStatus.SUCCEEDED,
        coverage=AnalysisCoverage.COMPLETE,
    )
    reopened = decide_lifecycle(
        RiskLifecycleState.RESOLVED,
        candidate_present=True,
        status=AnalysisStatus.SUCCEEDED,
        coverage=AnalysisCoverage.COMPLETE,
    )

    assert (detected.next_state, detected.event_type) == (
        RiskLifecycleState.NEW,
        RiskEventType.DETECTED,
    )
    assert (confirmed.next_state, confirmed.event_type) == (
        RiskLifecycleState.EXISTING,
        RiskEventType.CONFIRMED,
    )
    assert (resolved.next_state, resolved.event_type) == (
        RiskLifecycleState.RESOLVED,
        RiskEventType.RESOLVED,
    )
    assert (reopened.next_state, reopened.event_type) == (
        RiskLifecycleState.EXISTING,
        RiskEventType.REOPENED,
    )


def test_review_disposition_does_not_take_or_change_lifecycle_state() -> None:
    decision = decide_review(ReviewDisposition.UNREVIEWED, ReviewDisposition.EXCLUDED)
    assert decision.changed
    assert decision.event_type is RiskEventType.REVIEW_DISPOSITION_CHANGED
    assert not hasattr(decision, "lifecycle_state")
