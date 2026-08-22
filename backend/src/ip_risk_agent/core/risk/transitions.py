"""Pure Risk lifecycle and review decision functions."""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts import AnalysisCoverage, AnalysisStatus
from iprisk_contracts.common import AnalysisType

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


def absence_can_resolve(analysis_type: AnalysisType, candidate_count: int) -> bool:
    """후보가 없다는 사실만으로 기존 Risk 를 해소해도 되는가.

    ## 왜 이 규칙이 필요한가

    의존성 파일을 읽다가 **읽기가 망가지면 결과가 "선언 0 건" 으로 나온다.** 조각화가
    매니페스트를 쪼개도, redaction 이 패키지 이름을 바꿔도, 파서가 실패를 삼켜도, 게이트가
    입력을 잘라도 똑같이 0 건이다. 그리고 0 건은 실패가 아니라 ``SUCCEEDED`` + ``COMPLETE``
    로 올라오므로 :func:`analysis_is_authoritative` 를 통과한다. 그러면 그 파일의 라이선스
    Risk 가 **전부 "해소되었다" 로 닫힌다.**

    위험을 놓치는 것이 아니라 **위험이 사라졌다고 적극적으로 오보하는 것**이라 더 나쁘다.
    알림도 0 건이라 아무도 모른다.

    ## 경로를 세지 않고 결말을 막는다

    망가지는 길은 넷이고 앞으로 더 생길 수 있다. 그래서 길마다 막지 않고 **결말 하나를**
    막는다. 의존성 파일에서 선언이 하나도 안 나온 결과는 coverage 가 무엇이든 해소 권한을
    갖지 못한다. 아직 모르는 다섯 번째 경로가 있어도 같이 걸린다.

    ## 선언이 하나라도 있으면 막지 않는다

    ``candidate_count > 0`` 이면 파일은 제대로 읽혔고, 그중 특정 패키지가 목록에서 빠진 것은
    **사람이 실제로 의존성을 지운 것**이다. 그건 정상적인 해소이므로 그대로 둔다. 막는 것은
    "통째로 0 건" 이라는 전이 하나뿐이다.

    ## 지금은 예외를 두지 않는다

    사람이 의존성을 전부 지운 경우까지 함께 막히므로 해소되어야 할 Risk 가 열린 채 남는다.
    그것은 화면에 보이는 과경보이지 조용한 유실이 아니다. 둘을 가르려면 파서가 "못 읽었다"
    와 "선언 구역이 비어 있다" 를 구분해야 하는데, 지금은 구분하지 못한다. 구분이 생기면
    그때 예외를 연다.

    특허 경로에는 적용하지 않는다. 문서에서 후보가 사라지는 것은 파싱 손실이 아니라 판정
    변화이고, 그쪽은 애초에 선언을 세는 구조가 아니다.
    """
    if analysis_type is not AnalysisType.LICENSE:
        return True
    return candidate_count > 0


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
