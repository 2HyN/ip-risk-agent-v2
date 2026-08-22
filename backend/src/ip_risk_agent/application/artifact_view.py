"""artifact 하나의 **지금 상태**를 고르는 규칙.

한 번의 편집으로 소스가 판본을 여럿 만들면 변경도 여럿이 되고 분석도 여럿 돈다.
마지막 하나만 살아남고 나머지는 밀려서 끝난다. 그래서 "이 문서가 지금 어떤
상태인가" 는 기록을 세어서는 답할 수 없고, **지금 소스에 있는 판본을 맡은 실행**
하나를 골라야 답할 수 있다.

화면 여러 곳이 같은 질문을 한다. 규칙이 곳마다 다르면 같은 문서가 Sources 에서는
정상인데 Overview 에서는 실패로 보인다 — 실제로 그랬다.
"""

from __future__ import annotations

#: 밀려서 끝난 실행의 코드. 결함이 아니라 새 판본이 대신 맡았다는 뜻이다.
SUPERSEDED_FAILURE = "SOURCE:REVISION_SUPERSEDED"


def current_change_for_artifact(changes, state):
    """artifact 가 지금 보여 줄 변경. 없으면 ``None``.

    **지금 소스에 있는 판본**을 맡은 변경이다. "가장 최근에 갱신된" 것을 고르면
    뒤늦게 실패한 옛 판본이 아직 돌고 있는 새 판본을 덮는다.

    지금 판본을 맡은 변경이 아직 없으면(감지 직전) 가장 늦게 관측된 것을 준다.
    """
    if not changes:
        return None
    latest_revision = None if state is None else state.latest_revision
    if latest_revision is not None:
        current = [item for item in changes if item.revision == latest_revision]
        if current:
            return max(current, key=lambda item: (item.observed_at, item.id))
    return max(changes, key=lambda item: (item.observed_at, item.id))


def latest_job(jobs):
    """한 변경의 실행 중 마지막 것. 재검사는 같은 변경에 실행을 덧붙인다."""
    return max(jobs, key=lambda job: (job.created_at, job.id), default=None)


def needs_attention(job) -> bool:
    """사람이 볼 필요가 있는 실패인가.

    밀려서 끝난 것은 세지 않는다. 새 판본이 이미 그 자리를 맡았고 사람이 할 일이
    없다. 그것까지 세면 문서를 한 번 고칠 때마다 "분석 실패" 가 늘고, 뒤이어
    성공해도 줄지 않는다.
    """
    if job is None:
        return False
    return job.status.value == "FAILED" and job.failure_safe != SUPERSEDED_FAILURE


__all__ = [
    "SUPERSEDED_FAILURE",
    "current_change_for_artifact",
    "latest_job",
    "needs_attention",
]
