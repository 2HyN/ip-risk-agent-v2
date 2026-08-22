"""artifact 카드가 어느 변경을 보여 주는가.

한 번의 편집으로 Drive 가 판본을 여러 개 만들면 변경도 여러 개가 되고, 분석도
여러 개가 동시에 돈다. 옛 판본을 맡은 실행은 새 판본에 밀려 실패로 끝나는데,
그 실패가 **나중에** 기록되므로 "가장 최근에 갱신된 변경" 을 고르면 아직 돌고
있는 새 판본을 덮는다.

실제로 문단 하나를 추가했을 때 판본 네 개가 2 분 안에 만들어졌고, 화면에는 최신
판본이 분석 중인데도 옛 판본의 실패가 보였다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ip_risk_agent.application.artifact_view import (
    SUPERSEDED_FAILURE,
    latest_job,
    needs_attention,
)
from ip_risk_agent.application.artifact_view import (
    current_change_for_artifact as _current_change,
)

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Change:
    id: str
    revision: str
    observed_at: datetime
    #: 실패가 기록된 시각. 옛 판본은 새 판본보다 **늦게** 끝날 수 있다.
    updated_at: datetime


@dataclass(frozen=True)
class _State:
    latest_revision: str | None


#: 옛 판본. 먼저 관측됐지만 새 판본에 밀려 **나중에** 실패로 끝났다.
OLD = _Change("change-old", "rev-1", NOW, NOW + timedelta(minutes=10))
#: 지금 소스에 있는 판본. 나중에 관측됐고 아직 돌고 있다.
NEW = _Change("change-new", "rev-2", NOW + timedelta(seconds=30), NOW + timedelta(minutes=1))
#: 늦게 도착했지만 가리키는 판본은 이미 지난 것.
LATE_BUT_STALE = _Change(
    "change-late", "rev-1", NOW + timedelta(minutes=5), NOW + timedelta(minutes=5)
)


def test_the_change_for_the_revision_the_source_has_now_is_chosen() -> None:
    # 순서를 뒤집어 넣어도 결과가 같아야 한다. 목록 순서는 의미가 없다.
    assert _current_change([OLD, NEW], _State("rev-2")) is NEW
    assert _current_change([NEW, OLD], _State("rev-2")) is NEW


def test_a_stale_revision_does_not_win_by_finishing_later() -> None:
    """옛 판본이 늦게 끝났다는 이유로 화면을 차지하면 안 된다.

    ``OLD`` 의 갱신 시각이 ``NEW`` 보다 뒤다. 갱신 시각으로 고르면 이 시험이
    깨진다 — 배포에서 실제로 그렇게 골라 실패가 화면에 남았다.
    """
    assert OLD.updated_at > NEW.updated_at, "이 시험은 옛 것이 늦게 끝난 상황을 전제한다"
    assert _current_change([OLD, NEW], _State("rev-2")) is NEW


def test_a_change_that_arrived_later_for_an_older_revision_does_not_win() -> None:
    """늦게 도착했다고 지금 판본이 되지는 않는다.

    고르는 기준은 도착 순서가 아니라 **지금 소스에 있는 판본**이다.
    """
    assert _current_change([NEW, LATE_BUT_STALE], _State("rev-2")) is NEW


def test_the_latest_observed_change_is_used_when_the_revision_is_unknown() -> None:
    """감지 직전이라 지금 판본을 맡은 변경이 아직 없을 수 있다."""
    assert _current_change([OLD, NEW], _State(None)) is NEW
    assert _current_change([OLD, NEW], None) is NEW
    assert _current_change([OLD, NEW], _State("rev-3")) is NEW


def test_an_artifact_with_no_change_has_nothing_to_show() -> None:
    assert _current_change(None, _State("rev-1")) is None
    assert _current_change([], _State("rev-1")) is None


# --------------------------------------------------------------- 실패 집계


@dataclass(frozen=True)
class _Status:
    value: str


@dataclass(frozen=True)
class _Job:
    id: str
    created_at: datetime
    status: _Status
    failure_safe: str | None


def _job(name: str, status: str, failure: str | None = None, offset: int = 0) -> _Job:
    return _Job(name, NOW + timedelta(seconds=offset), _Status(status), failure)


def test_a_run_pushed_aside_by_a_newer_revision_is_not_a_failure_to_show() -> None:
    """문서를 한 번 고칠 때마다 "분석 실패" 가 늘고 성공해도 줄지 않았다.

    밀려서 끝난 실행은 새 판본이 그 자리를 맡았다는 뜻이다. 사람이 할 일이 없다.
    """
    assert not needs_attention(_job("j1", "FAILED", SUPERSEDED_FAILURE))


def test_a_real_failure_is_still_shown() -> None:
    assert needs_attention(_job("j1", "FAILED", "INTERNAL:UNEXPECTED_PIPELINE_FAILURE"))
    assert needs_attention(_job("j1", "FAILED", None))


def test_a_finished_or_missing_run_is_not_a_failure() -> None:
    assert not needs_attention(_job("j1", "SUCCEEDED"))
    assert not needs_attention(_job("j1", "INCONCLUSIVE"))
    assert not needs_attention(None)


def test_the_last_run_of_a_change_decides() -> None:
    """재검사는 같은 변경에 실행을 덧붙인다. 옛 시도가 결과를 말하면 안 된다."""
    first = _job("j1", "FAILED", "INTERNAL:UNEXPECTED_PIPELINE_FAILURE", offset=0)
    second = _job("j2", "SUCCEEDED", offset=60)
    assert latest_job([first, second]) is second
    assert latest_job([second, first]) is second
    assert not needs_attention(latest_job([first, second]))
    assert latest_job([]) is None
