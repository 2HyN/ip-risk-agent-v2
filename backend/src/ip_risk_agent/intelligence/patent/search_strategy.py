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
FIELDED_V1 = "fielded_v1"
FIELDED_V2 = "fielded_v2"

COMPARE_BASELINE = "baseline"
COMPARE_RAG = "rag"

_SEARCH_STRATEGIES = (BASELINE, EXPANDED_V1, FIELDED_V1, FIELDED_V2)
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
    #: KIPRIS 검색 필드. ``None`` 이면 getWordSearch(전문 검색), 필드 튜플이면
    #: getAdvancedSearch(항목별검색)로 필드마다 검색해 병합한다. 이 값은 분석기가
    #: 아니라 **KiprisClient 를 만드는 조립부**가 읽는다 — 검색 채널은 클라이언트
    #: 속성이기 때문이다 (kipris.KiprisClient search_fields 참조).
    search_fields: tuple[str, ...] | None = None
    #: 3단어 질의를 2단어 부분조합으로 확장한다 (extraction.expand_queries).
    #: AND 검색의 어휘 민감성을 깎는다 — 골든셋 실측에서 정확 질의가 인용 문헌을
    #: 못 데려온 원인 후보였다.
    expand_queries: bool = False
    #: 순위를 BM25 어휘 재순위로 한다 (candidate_rank.rank_candidates_bm25).
    #: use_rrf 보다 우선한다. 근거는 candidate_rank.RANK_VERSION_BM25 주석.
    use_bm25: bool = False


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

#: 필드별 검색 + 질의 확장. 골든셋 실측이 근거다 — 전문(getWordSearch) AND 검색은
#: 2단어 질의도 8,166건 속에 인용 문헌을 묻어 버리지만(60위 밖), 같은 질의를
#: 제목 필드로 좁히면 19건 중 4위였다. 초록 필드가 재현을 보충한다(394건 중 9위).
#: getAdvancedSearch 는 docsCount 를 20 까지 존중하므로 rows=20 이 실효 상한이다.
#: 0-hit 완화는 켜지 않는다 — 질의 확장이 같은 문제(어휘 민감성)를 앞단에서
#: 깎고, 완화는 전문 검색의 손잡이라 필드 검색과 겹치면 호출만 는다.
FIELDED_V1_PLAN = SearchPlan(
    name=FIELDED_V1,
    version="search_fielded_v1",
    extract_prompt="patent_extract_v3",
    max_queries=8,
    rows=20,
    relax_zero_hits=False,
    use_rrf=True,
    compare_cap=8,
    stage_deadline_seconds=90.0,
    search_fields=("inventionTitle", "astrtCont"),
    expand_queries=True,
)

#: 손실 회계(계획 문서 §7.2)의 처방 두 가지를 fielded_v1 위에 얹는다.
#:
#:   * rows 60 — getAdvancedSearch 는 pageNo/numOfRows 로 깊이가 열린다
#:     (실측). 인용 문헌들이 21~60위 구간에 실재해, 풀 천장이 4/25 → 10/25.
#:   * BM25 재순위 — 커진 풀의 소음은 위치가 아니라 어휘로 거른다. 고정 풀
#:     ablation 에서 recall@8 1/25(현행) → 4/25.
FIELDED_V2_PLAN = SearchPlan(
    name=FIELDED_V2,
    version="search_fielded_v2",
    extract_prompt="patent_extract_v3",
    max_queries=8,
    rows=60,
    relax_zero_hits=False,
    use_rrf=False,
    compare_cap=8,
    stage_deadline_seconds=90.0,
    search_fields=("inventionTitle", "astrtCont"),
    expand_queries=True,
    use_bm25=True,
)

_PLANS = {
    plan.name: plan
    for plan in (BASELINE_PLAN, EXPANDED_V1_PLAN, FIELDED_V1_PLAN, FIELDED_V2_PLAN)
}


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
    "FIELDED_V1",
    "FIELDED_V1_PLAN",
    "FIELDED_V2",
    "FIELDED_V2_PLAN",
    "SearchPlan",
    "plan_for",
    "require_compare_strategy",
]
