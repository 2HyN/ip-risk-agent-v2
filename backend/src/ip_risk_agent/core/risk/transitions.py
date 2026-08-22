"""Pure Risk lifecycle and review decision functions."""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts import AnalysisCoverage, AnalysisStatus

from ..common import DomainInvariantError
from .models import ReviewDisposition, RiskEventType, RiskLifecycleState

#: 사람이 스스로 고를 수 있는 처분. ``EXCLUDED`` 는 여기에 없다.
#:
#: ``EXCLUDED`` 는 workspace 삭제, 파일 추적 중단, mount 일시중지처럼 **사용자 판단
#: 밖의 외적 요인**으로 관리가 끝났다는 뜻이다. 추적이 이미 끊긴 Risk 를 두고 계속
#: 지켜볼지 사람이 고르는 것은 뜻이 통하지 않으므로 그 처분은 시스템만 붙인다.
#: 사람이 스스로 감시를 그만두는 것은 ``ACCEPTED_RISK`` 다.
USER_SELECTABLE_DISPOSITIONS = frozenset(
    {
        ReviewDisposition.UNREVIEWED,
        ReviewDisposition.MONITORING,
        ReviewDisposition.ACCEPTED_RISK,
    }
)


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


def decide_user_review(
    previous_disposition: ReviewDisposition,
    next_disposition: ReviewDisposition,
) -> ReviewDecision:
    """사람이 내리는 처분 변경. 시스템 전용 처분은 여기서 막는다.

    ``decide_review`` 는 시스템 전이도 함께 쓰므로 제한을 두지 않는다. 사람이 부르는
    경로만 이 함수를 지나가게 해서, 어떤 API 를 거치든 ``EXCLUDED`` 를 직접 붙일 수
    없게 한다.
    """
    if next_disposition not in USER_SELECTABLE_DISPOSITIONS:
        raise DomainInvariantError(
            "review disposition cannot be chosen by a reviewer"
        )
    if previous_disposition is ReviewDisposition.EXCLUDED:
        # 추적이 이미 끊긴 Risk 를 두고 계속 지켜볼지 사람이 고르는 것은 뜻이 통하지
        # 않는다. 다시 검토 대상이 되는 길은 그 파일을 다시 추적하는 것뿐이고,
        # 그때는 `should_revive` 가 UNREVIEWED 로 되돌린다.
        raise DomainInvariantError(
            "an excluded risk is reviewable only after tracking resumes"
        )
    return decide_review(previous_disposition, next_disposition)


@dataclass(frozen=True, slots=True)
class ExclusionDecision:
    """추적이 외적으로 끝났을 때의 전이."""

    previous_state: RiskLifecycleState
    next_state: RiskLifecycleState
    previous_disposition: ReviewDisposition
    next_disposition: ReviewDisposition

    @property
    def changed(self) -> bool:
        return (
            self.previous_state is not self.next_state
            or self.previous_disposition is not self.next_disposition
        )


def decide_exclusion(
    previous_state: RiskLifecycleState,
    previous_disposition: ReviewDisposition,
) -> ExclusionDecision:
    """파일 추적 중단·mount 일시중지처럼 관리가 외적으로 끝났을 때 부른다.

    ``RESOLVED`` 로 닫고 처분을 ``EXCLUDED`` 로 바꾼다. 근거와 이력은 그대로 남으므로
    감사는 온전하다. 이미 제외된 Risk 를 다시 제외하는 것은 아무것도 바꾸지 않는다.
    """
    return ExclusionDecision(
        previous_state=previous_state,
        next_state=RiskLifecycleState.RESOLVED,
        previous_disposition=previous_disposition,
        next_disposition=ReviewDisposition.EXCLUDED,
    )


def should_revive(previous_disposition: ReviewDisposition) -> bool:
    """제외됐던 Risk 를 다시 살려야 하는지.

    같은 workspace 의 같은 파일이 다시 추적 대상이 되면 이전 Risk 를 그대로 되살린다.
    새로 만들지 않는 이유는 그 파일의 이력이 한 줄로 이어져야 하기 때문이다. 다만
    제외되어 있던 동안의 판단은 더 이상 유효하지 않으므로 ``NEW`` / ``UNREVIEWED``
    에서 다시 시작한다.
    """
    return previous_disposition is ReviewDisposition.EXCLUDED
