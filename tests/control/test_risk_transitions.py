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


def test_a_reviewer_cannot_choose_the_excluded_disposition() -> None:
    """EXCLUDED 는 외적 요인으로 관리가 끝났다는 뜻이라 사람이 고를 수 없다.

    추적이 이미 끊긴 Risk 를 두고 계속 지켜볼지 사람이 판단하는 것은 뜻이 통하지
    않는다. 사람이 스스로 감시를 그만두는 것은 ACCEPTED_RISK 다.
    """
    from ip_risk_agent.core.common import DomainInvariantError
    from ip_risk_agent.core.risk import decide_user_review

    for allowed in (
        ReviewDisposition.UNREVIEWED,
        ReviewDisposition.MONITORING,
        ReviewDisposition.ACCEPTED_RISK,
    ):
        decision = decide_user_review(ReviewDisposition.UNREVIEWED, allowed)
        assert decision.next_disposition is allowed

    with pytest.raises(DomainInvariantError):
        decide_user_review(ReviewDisposition.MONITORING, ReviewDisposition.EXCLUDED)

    # 반대 방향도 막는다. 추적이 끊긴 Risk 를 사람이 되살리는 길은 없다.
    with pytest.raises(DomainInvariantError):
        decide_user_review(ReviewDisposition.EXCLUDED, ReviewDisposition.MONITORING)


def test_exclusion_closes_the_risk_without_erasing_it() -> None:
    from ip_risk_agent.core.risk import decide_exclusion

    decision = decide_exclusion(
        RiskLifecycleState.EXISTING, ReviewDisposition.MONITORING
    )
    assert decision.next_state is RiskLifecycleState.RESOLVED
    assert decision.next_disposition is ReviewDisposition.EXCLUDED
    assert decision.changed


def test_only_an_excluded_risk_is_revived_when_tracking_resumes() -> None:
    """다시 추적하게 되면 이전 Risk 를 되살린다. 사람 처분은 되살리지 않는다."""
    from ip_risk_agent.core.risk import should_revive

    assert should_revive(ReviewDisposition.EXCLUDED)
    for kept in (
        ReviewDisposition.UNREVIEWED,
        ReviewDisposition.MONITORING,
        ReviewDisposition.ACCEPTED_RISK,
    ):
        assert not should_revive(kept)


# --------------------------------------------------------------------- 0-L


def test_a_dependency_result_with_no_declarations_cannot_resolve() -> None:
    """망가진 읽기와 "위험 없음" 이 같은 모양으로 올라온다.

    조각화·redaction·삼킨 파싱 실패·게이트 절단이 전부 선언 0 건을 만들고, 그 결과는
    ``SUCCEEDED`` + ``COMPLETE`` 라 권위를 얻는다. 길마다 막지 않고 결말 하나를 막는다.
    """
    from iprisk_contracts.common import AnalysisType

    from ip_risk_agent.core.risk import absence_can_resolve

    assert absence_can_resolve(AnalysisType.LICENSE, 0) is False


def test_one_declaration_is_enough_to_trust_what_is_missing() -> None:
    """파일이 읽혔다면 목록에서 빠진 패키지는 사람이 실제로 지운 것이다."""
    from iprisk_contracts.common import AnalysisType

    from ip_risk_agent.core.risk import absence_can_resolve

    assert absence_can_resolve(AnalysisType.LICENSE, 1) is True


def test_the_rule_does_not_reach_the_patent_path() -> None:
    """문서에서 후보가 사라지는 것은 파싱 손실이 아니라 판정 변화다."""
    from iprisk_contracts.common import AnalysisType

    from ip_risk_agent.core.risk import absence_can_resolve

    assert absence_can_resolve(AnalysisType.PATENT, 0) is True
