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
FIELDED_V3 = "fielded_v3"
FIELDED_V4 = "fielded_v4"
FIELDED_V5 = "fielded_v5"

COMPARE_BASELINE = "baseline"
COMPARE_RAG = "rag"

_SEARCH_STRATEGIES = (BASELINE, EXPANDED_V1, FIELDED_V1, FIELDED_V2, FIELDED_V3, FIELDED_V4)
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
    #: 정밀꼬리 판정 확장 — cap 아래 이 순위까지 내려가며 "제목 필드 ×
    #: 결과집합 ≤ judge_tail_total_cap 질의" 적중 후보를 판정 대상에 추가한다.
    #: 0 이면 끔. 근거: 고정 풀 실측에서 놓친 인용들이 9~24위의 정밀 제목
    #: 적중에 몰려 있었고(순위 16·19·23), 이 필터는 그 구간에서 문서당 평균
    #: +2.7건만 통과시키며 recall@판정 10→13/83 (+30%). 단순 cap 확대는
    #: cap 16 에도 +1 뿐이라 비효율이 실측됐다.
    judge_tail_to: int = 0
    judge_tail_total_cap: int = 30
    #: 질의 확장(2단어 부분조합)의 상한. v4 는 프롬프트가 계열을 늘려 base
    #: 질의가 많아지므로 함께 올린다 — cap 선착순 절단으로 도달 가능 확장이
    #: 잘린 사례가 실측됐다.
    expansion_cap: int = 15


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

#: fielded_v2 + 정밀꼬리 판정 확장. 검색·순위는 v2 그대로 두고(깊이 120 은
#: 실측에서 오히려 잡음 — rows 60 유지), 판정 대상만 9~24위의 정밀 제목
#: 적중으로 넓힌다. 4-렌즈 분석과 고정 풀 재현으로 확정된 조합이다.
FIELDED_V3_PLAN = SearchPlan(
    name=FIELDED_V3,
    version="search_fielded_v3",
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
    judge_tail_to=24,
    judge_tail_total_cap=30,
)

#: fielded_v3 + 질의 생성 v4. 골든셋 도달성 마이닝(3렌즈·라이브 probe 100회)
#: 의 처방이다 — A2 28건 중 20건, B 6건 중 4~5건은 어휘·조합이 실재하는데
#: 질의 생성이 못 만든 것이 원인으로 확정됐다. 프롬프트 v4 는 5계열(정식
#: 명칭 / 구성요소·수단 교차 / 문제·효과 어휘 / 동의어·표기 이형 / 앵커
#: 해제·대칭)로 10~14개를 만들고, 클라이언트는 `*` AND 연산자와 필드별
#: 무절단 병합을 쓴다 (수집 아티팩트로 인용 12건이 잘리던 결함 수정).
FIELDED_V4_PLAN = SearchPlan(
    name=FIELDED_V4,
    version="search_fielded_v4",
    extract_prompt="patent_extract_v4",
    max_queries=14,
    rows=60,
    relax_zero_hits=False,
    use_rrf=False,
    compare_cap=8,
    stage_deadline_seconds=120.0,
    search_fields=("inventionTitle", "astrtCont"),
    expand_queries=True,
    use_bm25=True,
    judge_tail_to=24,
    judge_tail_total_cap=30,
    expansion_cap=24,
)

#: v4 + **질의 결과집합 대역 교정.** 손잡이는 v4 그대로이고 추출 프롬프트만
#: 바뀐다 — 이번 변경의 원인 귀속을 하나로 묶기 위해서다.
#:
#: 근거: 골든셋 샘플(출원 10 · 인용 16)에서 v4 가 v3 에 졌다. 풀 진입
#: 2/16 vs 6/16, 풀 천장 3 vs 6. 원인은 **과도한 협소화**로 특정됐다 —
#: 질의당 결과집합 중앙값이 v3 15건 vs v4 5건이었고, 오라클 곡선(질의
#: 812회)에서 10건 미만 구간의 적중률은 25% 로 10~30건(42%)·30~100건
#: (44%) 보다 낮다. "좁을수록 좋다" 가 아니라 대역이 있다.
#:
#: 순위층은 건드리지 않는다. 캐시된 풀 위에서 21개 변형을 스위프한 결과
#: (`sweep_search_rank.py`) 정밀꼬리 임계값은 10~1000 어디서도 적중이
#: 불변이었고, cap 16 만 +1 을 주되 판정 대상이 10.8 → 17.2 건으로 늘어
#: 전환율이 나빴다. BM25 를 끄면 0 으로 무너진다 — 순위층은 포화다.
FIELDED_V5_PLAN = SearchPlan(
    name=FIELDED_V5,
    version="search_fielded_v5",
    extract_prompt="patent_extract_v5",
    max_queries=FIELDED_V4_PLAN.max_queries,
    rows=FIELDED_V4_PLAN.rows,
    relax_zero_hits=FIELDED_V4_PLAN.relax_zero_hits,
    use_rrf=FIELDED_V4_PLAN.use_rrf,
    compare_cap=FIELDED_V4_PLAN.compare_cap,
    stage_deadline_seconds=FIELDED_V4_PLAN.stage_deadline_seconds,
    search_fields=FIELDED_V4_PLAN.search_fields,
    expand_queries=FIELDED_V4_PLAN.expand_queries,
    use_bm25=FIELDED_V4_PLAN.use_bm25,
    judge_tail_to=FIELDED_V4_PLAN.judge_tail_to,
    judge_tail_total_cap=FIELDED_V4_PLAN.judge_tail_total_cap,
    expansion_cap=FIELDED_V4_PLAN.expansion_cap,
)

_PLANS = {
    plan.name: plan
    for plan in (
        BASELINE_PLAN,
        EXPANDED_V1_PLAN,
        FIELDED_V1_PLAN,
        FIELDED_V2_PLAN,
        FIELDED_V3_PLAN,
        FIELDED_V4_PLAN,
        FIELDED_V5_PLAN,
    )
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
    "FIELDED_V3",
    "FIELDED_V3_PLAN",
    "FIELDED_V4",
    "FIELDED_V4_PLAN",
    "FIELDED_V5",
    "FIELDED_V5_PLAN",
    "SearchPlan",
    "plan_for",
    "require_compare_strategy",
]
