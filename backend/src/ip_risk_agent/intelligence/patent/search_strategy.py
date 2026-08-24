"""검색·대조 전략 스위치.

고도화 전략(`docs/PATENT_RAG_ENHANCEMENT_PLAN.md`)은 기존 방식을 삭제하지 않고
베이스라인으로 병존시킨다. 이 파일이 그 스위치의 실체다 — 계획(plan)을 주입하지
않으면 분석기는 현행 상수 그대로 동작한다.

## baseline 은 기록 문자열도 그대로다

베이스라인 계획의 ``version`` 은 ``None`` 이다. ``prompt_version`` 에 아무것도
연접하지 않는다는 뜻이다. 연접하면 배포 직후 모든 재검사에서 원인 귀속이
``ChangeCause.MODEL`` 로 오염된다 — 바뀐 것이 없는데 "모델이 바뀌었다"는 문장이
사용자에게 나간다 (계획 문서 §6-1).
"""

from __future__ import annotations

from dataclasses import dataclass

BASELINE = "baseline"
EXPANDED_V1 = "expanded_v1"

COMPARE_BASELINE = "baseline"
COMPARE_RAG = "rag"

_SEARCH_STRATEGIES = (BASELINE, EXPANDED_V1)
_COMPARE_STRATEGIES = (COMPARE_BASELINE, COMPARE_RAG)


@dataclass(frozen=True)
class SearchPlan:
    """검색 단계의 손잡이 묶음. 값 하나하나가 곧 전략의 정의다."""

    name: str
    #: ``prompt_version`` 에 연접할 전략 버전. ``None`` 이면 연접하지 않는다.
    version: str | None
    extract_prompt: str
    max_queries: int
    rows: int
    relax_zero_hits: bool
    use_rrf: bool
    compare_cap: int
    #: 검색 단계 전체의 벽시계 예산. 확장 전략은 질의 수가 많아 최악 지연이
    #: worker 요청 예산(300초)을 뚫을 수 있으므로 여기서 자른다 (계획 문서 §6-3).
    #: 초과분은 실패로 기록되어 coverage 가 PARTIAL 로 낮아진다.
    stage_deadline_seconds: float | None


#: 현행 그대로. 질의 5 × rows 5, 적중수·위치 정렬, cap 6.
BASELINE_PLAN = SearchPlan(
    name=BASELINE,
    version=None,
    extract_prompt="patent_extract_v2",
    max_queries=5,
    rows=5,
    relax_zero_hits=False,
    use_rrf=False,
    compare_cap=6,
    stage_deadline_seconds=None,
)

#: 유료 전환의 배당. 질의 12 × rows 30, 0-hit 완화, RRF 병합, cap 8.
EXPANDED_V1_PLAN = SearchPlan(
    name=EXPANDED_V1,
    version="search_expanded_v1",
    extract_prompt="patent_extract_v3",
    max_queries=12,
    rows=30,
    relax_zero_hits=True,
    use_rrf=True,
    compare_cap=8,
    stage_deadline_seconds=90.0,
)

_PLANS = {plan.name: plan for plan in (BASELINE_PLAN, EXPANDED_V1_PLAN)}


def plan_for(name: str) -> SearchPlan:
    """이름으로 계획을 찾는다. 오타가 조용히 베이스라인으로 떨어지지 않게 막는다."""
    plan = _PLANS.get(name)
    if plan is None:
        raise ValueError(
            f"unknown patent search strategy {name!r}; expected one of {_SEARCH_STRATEGIES}"
        )
    return plan


def require_compare_strategy(name: str) -> str:
    if name not in _COMPARE_STRATEGIES:
        raise ValueError(
            f"unknown patent compare strategy {name!r}; expected one of {_COMPARE_STRATEGIES}"
        )
    return name


__all__ = [
    "BASELINE",
    "BASELINE_PLAN",
    "COMPARE_BASELINE",
    "COMPARE_RAG",
    "EXPANDED_V1",
    "EXPANDED_V1_PLAN",
    "SearchPlan",
    "plan_for",
    "require_compare_strategy",
]
