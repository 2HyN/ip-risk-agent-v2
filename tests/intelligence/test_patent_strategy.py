"""검색 전략(확장·완화·RRF·버킷) 회귀 테스트.

베이스라인 보존이 1급 요구다 — 계획을 넣지 않은 분석기가 현행과 같은 인자로
검색하고 같은 기록 문자열을 내는 것을 스파이로 고정한다 (계획 문서 §3, §6-1).
"""

from __future__ import annotations

import asyncio
from xml.etree.ElementTree import fromstring

import pytest

from iprisk_contracts.common import AnalysisStatus, AnalysisType, ArtifactKind

from ip_risk_agent.intelligence.common.errors import (
    FailureCategory,
    ProviderFailureError,
)
from ip_risk_agent.intelligence.gemini.client import ScriptedModelClient
from ip_risk_agent.intelligence.gemini.schemas import TechnicalExtraction
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.candidate_rank import (
    rank_candidates,
    rank_candidates_bm25,
    rank_candidates_rrf,
)
from ip_risk_agent.intelligence.patent.ephemeral_index import tokenize
from ip_risk_agent.intelligence.patent.extraction import clamp_queries, query_families
from ip_risk_agent.intelligence.patent.kipris import (
    ADVANCED_SEARCH_PATH,
    KiprisClient,
    PatentSearchHit,
)
from ip_risk_agent.intelligence.patent.query_builder import run_searches
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket
from ip_risk_agent.intelligence.patent.search_strategy import (
    BASELINE_PLAN,
    EXPANDED_V1_PLAN,
    FIELDED_V1_PLAN,
    FIELDED_V2_PLAN,
    FIELDED_V3_PLAN,
    plan_for,
    require_compare_strategy,
)

from test_license import make_artifact, run


def hit(number: str, query: str, *, ipc: str = "", relaxed: bool = False):
    metadata = {"ipc": ipc} if ipc else {}
    if relaxed:
        metadata["relaxed"] = "true"
    return PatentSearchHit(
        application_number=number, title=f"특허 {number}", query=query, metadata=metadata
    )


class SpyProvider:
    """호출된 (질의, rows) 를 기록하고 지정된 결과를 돌려준다."""

    def __init__(self, results: dict[str, list[PatentSearchHit]] | None = None):
        self._results = results or {}
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, rows: int = 5):
        self.calls.append((query, rows))
        return list(self._results.get(query, []))[:rows]

    async def fetch_detail(self, application_number: str):  # pragma: no cover
        raise AssertionError("이 테스트는 상세조회에 닿지 않는다")


# ------------------------------------------------------------------ plan


def test_plan_whitelist_rejects_typos():
    with pytest.raises(ValueError):
        plan_for("expanded")  # 오타가 조용히 베이스라인으로 떨어지면 안 된다
    with pytest.raises(ValueError):
        require_compare_strategy("rag_v2")


def test_baseline_plan_matches_current_constants():
    assert BASELINE_PLAN.max_queries == 5
    assert BASELINE_PLAN.rows == 5
    assert BASELINE_PLAN.compare_cap == 6
    assert BASELINE_PLAN.version is None  # prompt_version 무연접 — 귀속 오염 방지


def test_clamp_queries_honors_the_plan_cap():
    queries = [f"검색어 조합 {index}" for index in range(15)]
    assert len(clamp_queries(queries)) == 5
    assert len(clamp_queries(queries, max_queries=EXPANDED_V1_PLAN.max_queries)) == 12


# ------------------------------------------------------------------ 완화


def test_zero_hit_three_word_query_relaxes_to_two_words():
    provider = SpyProvider(
        {"화자 분리": [hit("100", "화자 분리")]}  # 완화 질의만 결과가 있다
    )
    outcome = run(
        run_searches(
            provider, ["화자 분리 알고리즘"], rows=30, relax_zero_hits=True
        )
    )
    assert provider.calls == [("화자 분리 알고리즘", 30), ("화자 분리", 30)]
    hits = outcome.hits_by_query["화자 분리 알고리즘"]
    assert [h.application_number for h in hits] == ["100"]
    # 완화 히트는 원 질의로 귀속되고 표식이 붙는다.
    assert hits[0].query == "화자 분리 알고리즘"
    assert hits[0].metadata["relaxed"] == "true"
    assert outcome.relaxations == {"화자 분리 알고리즘": "화자 분리"}
    assert outcome.relax_recovered == 1


def test_relaxation_does_not_mutate_provider_objects():
    """캐시가 돌려준 객체를 변이하면 다른 질의의 결과가 오염된다 (§6-2)."""
    shared = hit("100", "화자 분리")
    provider = SpyProvider({"화자 분리": [shared]})
    run(run_searches(provider, ["화자 분리 알고리즘"], relax_zero_hits=True))
    assert "relaxed" not in shared.metadata
    assert shared.query == "화자 분리"


def test_two_word_zero_hit_stays_zero():
    provider = SpyProvider()
    outcome = run(run_searches(provider, ["화자 분리"], relax_zero_hits=True))
    assert provider.calls == [("화자 분리", 5)]
    assert outcome.hits_by_query["화자 분리"] == []
    assert outcome.relaxations == {}


def test_converging_relaxations_attach_to_the_first_query_only():
    provider = SpyProvider({"음성 인식": [hit("200", "음성 인식")]})
    outcome = run(
        run_searches(
            provider,
            ["음성 인식 장치", "음성 인식 방법"],
            relax_zero_hits=True,
        )
    )
    # 같은 완화 질의("음성 인식")는 정렬 순서상 첫 원질의에만 귀속된다 —
    # 같은 검색 1회가 다중 질의 합의 신호로 부풀지 않게.
    relaxed_calls = [call for call in provider.calls if call[0] == "음성 인식"]
    assert len(relaxed_calls) == 1
    assert list(outcome.relaxations) == ["음성 인식 방법"] or list(
        outcome.relaxations
    ) == ["음성 인식 장치"]
    recovered = [
        query for query, hits in outcome.hits_by_query.items() if hits
    ]
    assert len(recovered) == 1


def test_relaxation_skips_targets_that_are_original_queries():
    provider = SpyProvider({"음성 인식": [hit("200", "음성 인식")]})
    run(
        run_searches(
            provider, ["음성 인식", "음성 인식 장치"], relax_zero_hits=True
        )
    )
    # "음성 인식 장치" 의 완화 목표가 이미 원질의라 재검색하지 않는다.
    assert provider.calls.count(("음성 인식", 5)) == 1


def test_stage_deadline_records_timeouts_as_failures():
    class SlowProvider:
        async def search(self, query: str, *, rows: int = 5):
            await asyncio.sleep(30)
            return []

        async def fetch_detail(self, application_number: str):  # pragma: no cover
            raise AssertionError

    outcome = run(
        run_searches(
            SlowProvider(), ["느린 질의 하나"], stage_deadline_seconds=0.05
        )
    )
    # 조용히 줄이는 것이 아니라 실패로 기록된다 → coverage 가 PARTIAL 로 낮아진다.
    assert not outcome.hits_by_query
    assert len(outcome.failures) == 1
    assert outcome.failures[0].category is FailureCategory.TIMEOUT


# ------------------------------------------------------------------ RRF


def _shuffled(mapping: dict):
    keys = sorted(mapping, reverse=True)
    return {key: mapping[key] for key in keys}


def test_rrf_is_deterministic_under_input_order():
    hits_by_query = {
        "질의 가": [hit("300", "질의 가"), hit("100", "질의 가")],
        "질의 나": [hit("100", "질의 나"), hit("200", "질의 나")],
    }
    first = [c.application_number for c in rank_candidates_rrf(hits_by_query)]
    second = [
        c.application_number for c in rank_candidates_rrf(_shuffled(hits_by_query))
    ]
    assert first == second
    assert first[0] == "100"  # 두 질의에 걸린 후보가 앞


def test_rrf_matches_legacy_order_for_single_hit_candidates():
    """단일 적중 후보끼리 RRF 는 현행(위치 순)과 같은 순서를 낸다 (§6-10).

    이 함수의 가치는 단독 개선이 아니라 완화·IPC 채널의 융합 자리다 — 기대를
    정직하게 고정해 측정이 0 을 내도 설계가 반증되지 않게 한다.
    """
    hits_by_query = {
        "질의 가": [hit("300", "질의 가"), hit("100", "질의 가"), hit("200", "질의 가")],
    }
    legacy = [c.application_number for c in rank_candidates(hits_by_query)]
    rrf = [c.application_number for c in rank_candidates_rrf(hits_by_query, ipc_signal=False)]
    assert legacy == rrf


def test_relaxed_hits_carry_less_weight():
    hits_by_query = {
        "질의 가": [hit("100", "질의 가", relaxed=True)],
        "질의 나": [hit("200", "질의 나")],
    }
    ordered = rank_candidates_rrf(hits_by_query, ipc_signal=False)
    assert [c.application_number for c in ordered] == ["200", "100"]


def test_ipc_consistency_breaks_ties():
    hits_by_query = {
        "질의 가": [hit("100", "질의 가", ipc="G10L 25/00")],
        "질의 나": [hit("200", "질의 나", ipc="A63F 13/00")],
        "질의 다": [hit("300", "질의 다", ipc="G10L 15/00")],
    }
    ordered = rank_candidates_rrf(hits_by_query)
    # 전부 단일 적중·1위라 RRF 동점 — 지배 서브클래스(G10L 2표)와 일치하는
    # 후보가 앞선다. 불일치 후보도 제외되지 않고 뒤에 남는다.
    assert [c.application_number for c in ordered[:2]] == ["100", "300"]
    assert ordered[-1].application_number == "200"
    assert not ordered[-1].ipc_consistent


def test_rrf_scores_are_recorded_on_candidates():
    hits_by_query = {"질의 가": [hit("100", "질의 가")]}
    (candidate,) = rank_candidates_rrf(hits_by_query, ipc_signal=False)
    assert candidate.rrf_score > 0


# ------------------------------------------------------------------ 버킷


def test_token_bucket_paces_requests_with_injected_clock():
    now = {"value": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)
        now["value"] += seconds

    bucket = TokenBucket(
        2.0, capacity=1.0, clock=lambda: now["value"], sleep=fake_sleep
    )

    async def scenario():
        await bucket.acquire()  # 즉시
        await bucket.acquire()  # 0.5초 대기
        await bucket.acquire()  # 다시 0.5초 대기

    run(scenario())
    assert sleeps == pytest.approx([0.5, 0.5])


def test_token_bucket_rejects_nonpositive_rate():
    with pytest.raises(ValueError):
        TokenBucket(0)


# ------------------------------------------------------------------ fielded


def test_fielded_plan_constants():
    plan = plan_for("fielded_v1")
    assert plan is FIELDED_V1_PLAN
    assert plan.search_fields == ("inventionTitle", "astrtCont")
    assert plan.expand_queries is True
    assert plan.rows == 20  # getAdvancedSearch 가 존중하는 실측 상한
    assert plan.relax_zero_hits is False  # 확장이 어휘 민감성을 앞단에서 깎는다
    assert plan.use_rrf is True
    assert plan.version == "search_fielded_v1"


def test_baseline_and_expanded_plans_do_not_switch_channels():
    # 기존 두 계획의 동작 보존 — 필드 검색·질의 확장은 기본 꺼짐이다.
    assert BASELINE_PLAN.search_fields is None
    assert BASELINE_PLAN.expand_queries is False
    assert EXPANDED_V1_PLAN.search_fields is None
    assert EXPANDED_V1_PLAN.expand_queries is False


def _search_response(*numbers: str):
    items = "".join(
        f"<item><applicationNumber>{number}</applicationNumber>"
        f"<inventionTitle>특허 {number}</inventionTitle></item>"
        for number in numbers
    )
    return fromstring(
        "<response><header><resultCode>00</resultCode></header>"
        f"<body><items>{items}</items></body></response>"
    )


def test_fielded_search_merges_title_first_and_dedupes():
    client = KiprisClient(
        "test-key", client=object(), search_fields=("inventionTitle", "astrtCont")
    )
    calls: list[tuple[str, dict]] = []
    responses = [
        _search_response("1020200000001", "1020200000002"),  # 제목 필드
        _search_response("1020200000002", "1020200000003"),  # 초록 필드
    ]

    async def fake_get(path: str, params: dict):
        calls.append((path, dict(params)))
        return responses.pop(0)

    client._get = fake_get

    hits = run(client.search("셔터 연동", rows=20))

    # 제목 결과가 앞, 초록은 새 번호만 뒤에 붙는다 (인용 문헌 제목 4위 실측 근거).
    assert [hit.application_number for hit in hits] == [
        "1020200000001",
        "1020200000002",
        "1020200000003",
    ]
    assert [path for path, _ in calls] == [ADVANCED_SEARCH_PATH, ADVANCED_SEARCH_PATH]
    assert calls[0][1]["inventionTitle"] == "셔터 연동"
    assert calls[1][1]["astrtCont"] == "셔터 연동"
    # getAdvancedSearch 도 docsStart 는 무시된다(1페이지 반복 실측) —
    # 실제로 듣는 pageNo/numOfRows 를 쓴다.
    assert calls[0][1]["numOfRows"] == "20"
    assert calls[0][1]["pageNo"] == "1"


def test_fielded_plan_expands_queries_and_uses_plan_rows():
    model = ScriptedModelClient(
        [
            TechnicalExtraction(
                is_technical=True,
                technical_elements=["셔터 CCTV 연동"],
                search_queries=["셔터 CCTV 연동"],
                source_segment_ids=["seg-1"],
            )
        ]
    )
    provider = SpyProvider()  # 모든 질의 0건 — 상세조회에 닿지 않는다
    analyzer = PatentAnalyzer(
        provider,
        model,
        search_plan=FIELDED_V1_PLAN,
        compare_strategy="rag",
    )
    artifact = make_artifact(
        "셔터와 CCTV 를 연동하는 설계.",
        logical_path="/Google Drive user@example.com/docs/plan.md",
        kind=ArtifactKind.DOCUMENT_TEXT,
        analyzers=[AnalysisType.PATENT],
    )

    result = run(analyzer.analyze(artifact))

    assert result.status is AnalysisStatus.SUCCEEDED
    queries = [query for query, _ in provider.calls]
    # 원 질의가 앞(정밀 우선), 2단어 부분조합이 뒤따른다.
    assert queries[0] == "셔터 CCTV 연동"
    assert {"셔터 CCTV", "셔터 연동", "CCTV 연동"} <= set(queries)
    assert all(rows == FIELDED_V1_PLAN.rows for _, rows in provider.calls)
    # 기록 문자열에 전략 버전이 연접된다 — "그때의 후보 풀"을 되짚는 지문.
    assert "search_fielded_v1" in result.versions.prompt_version


def test_prior_art_cutoff_drops_future_hits_but_keeps_unknown_dates():
    from ip_risk_agent.intelligence.patent.analyzer import _drop_future_hits

    past = PatentSearchHit(
        application_number="1020190000001",
        title="과거 출원",
        query="q",
        metadata={"applicationDate": "2019.03.01"},
    )
    future = PatentSearchHit(
        application_number="1020230000002",
        title="미래 출원",
        query="q",
        metadata={"applicationDate": "20230501"},
    )
    unknown = PatentSearchHit(
        application_number="1020000000003", title="날짜 미상", query="q", metadata={}
    )
    hits_by_query = {"q": [past, future, unknown]}

    _drop_future_hits(hits_by_query, "20200601")

    # 미래 문서만 치운다 — 날짜를 모르는 히트는 정보 부족이지 탈락 사유가 아니다.
    assert hits_by_query["q"] == [past, unknown]


# ------------------------------------------------------------------ rank v2


def test_specific_query_hits_outweigh_broad_query_hits():
    """특이도 가중 — 19건 질의의 적중이 2,769건 질의의 적중보다 무겁다."""
    narrow = hit("100", "셔터 연동")
    narrow.metadata["search_total"] = "19"
    broad = hit("200", "CCTV 영상")
    broad.metadata["search_total"] = "2769"
    ordered = rank_candidates_rrf(
        {"셔터 연동": [narrow], "CCTV 영상": [broad]}, ipc_signal=False
    )
    assert [c.application_number for c in ordered] == ["100", "200"]


def test_expansion_variants_do_not_fake_consensus():
    """계열별 max — 같은 원 질의의 확장 변형 여럿에 걸려도 한 번으로 센다."""
    original = "셔터 경광등 연동"
    variants = ["셔터 경광등", "셔터 연동", "경광등 연동"]
    hits_by_query = {q: [hit("100", q)] for q in [original, *variants]}
    # 다른 계열 하나에 걸린 후보 — 위치는 더 낮다(2위).
    other = hit("200", "지하철 제어")
    hits_by_query["지하철 제어"] = [hit("300", "지하철 제어"), other]
    families = {q: original for q in [original, *variants]}
    families["지하철 제어"] = "지하철 제어"
    ordered = rank_candidates_rrf(
        hits_by_query, family_of=families, ipc_signal=False
    )
    ranks = {c.application_number: i for i, c in enumerate(ordered)}
    # 계열 1개×변형 4개(=1회)인 100 이, 계열 1개 2위인 200 을 크게 앞서지 않는다
    # — max 합산이므로 100 의 점수는 1/(60+1) 하나뿐이다.
    scores = {c.application_number: c.rrf_score for c in ordered}
    assert scores["100"] == pytest.approx(1 / 61, rel=1e-6)
    assert ranks["100"] < ranks["200"]  # 위치 우위만큼만 앞선다


def test_title_similarity_lifts_topically_close_candidates():
    """제목-원문 유사도 배수 — 원문 어휘를 공유하는 제목이 앞선다."""
    close = PatentSearchHit(
        application_number="100", title="방화셔터 연동 제어기", query="질의 가"
    )
    far = PatentSearchHit(
        application_number="200", title="영화 자막 시스템", query="질의 가"
    )
    source = frozenset(tokenize("지하철 역사의 방화셔터를 연동 제어하는 장치"))
    # far 가 위치상 앞이어도 유사도 배수가 뒤집는다.
    ordered = rank_candidates_rrf(
        {"질의 가": [far, close]},
        source_tokens=source,
        ipc_signal=False,
    )
    assert [c.application_number for c in ordered] == ["100", "200"]


def test_exclude_removes_self_from_pool():
    hits_by_query = {"질의 가": [hit("100", "질의 가"), hit("200", "질의 가")]}
    ordered = rank_candidates_rrf(
        hits_by_query, exclude=frozenset({"100"}), ipc_signal=False
    )
    assert [c.application_number for c in ordered] == ["200"]


def test_query_families_attribute_variants_to_first_superset():
    families = query_families(
        ["셔터 경광등 연동", "지하철 셔터 제어"],
        ["셔터 경광등 연동", "셔터 경광등", "셔터 연동", "지하철 셔터", "완전 다른 질의"],
    )
    assert families["셔터 경광등"] == "셔터 경광등 연동"
    assert families["셔터 연동"] == "셔터 경광등 연동"
    assert families["지하철 셔터"] == "지하철 셔터 제어"
    assert families["완전 다른 질의"] == "완전 다른 질의"


# ------------------------------------------------------------------ bm25 rank


def test_fielded_v2_plan_constants():
    plan = plan_for("fielded_v2")
    assert plan is FIELDED_V2_PLAN
    assert plan.rows == 60  # pageNo/numOfRows 실측으로 열린 깊이
    assert plan.use_bm25 is True
    assert plan.use_rrf is False
    assert plan.search_fields == ("inventionTitle", "astrtCont")
    assert plan.version == "search_fielded_v2"
    # 기존 계획들은 BM25 를 켜지 않는다 — 동작 보존.
    assert BASELINE_PLAN.use_bm25 is False
    assert EXPANDED_V1_PLAN.use_bm25 is False
    assert FIELDED_V1_PLAN.use_bm25 is False


def _hit_with_abstract(number: str, query: str, title: str, abstract: str):
    return PatentSearchHit(
        application_number=number, title=title, query=query, abstract=abstract
    )


def test_bm25_prefers_vocabulary_over_position():
    """원문 어휘를 공유하는 후보가 검색 위치가 낮아도 앞선다."""
    src = frozenset(tokenize("지하철 역사의 방화셔터를 연동 제어하는 장치"))
    far = _hit_with_abstract("200", "질의", "영화 자막 시스템", "자막을 출력한다")
    close = _hit_with_abstract(
        "100", "질의", "방화셔터 연동제어기", "방화셔터를 연동하여 제어한다"
    )
    ordered = rank_candidates_bm25(
        {"질의": [far, close]}, source_tokens=src, ipc_signal=False
    )
    assert [c.application_number for c in ordered] == ["100", "200"]
    assert ordered[0].bm25_score > 0.0


def test_bm25_falls_back_to_rrf_when_no_vocabulary_overlap():
    """원문 토큰 공유가 전무하면 검색 신호(RRF) 순서로 넘어간다."""
    src = frozenset(tokenize("완전히 무관한 어휘"))
    first = _hit_with_abstract("100", "질의", "제목 하나", "본문 하나")
    second = _hit_with_abstract("200", "질의", "제목 둘", "본문 둘")
    ordered = rank_candidates_bm25(
        {"질의": [first, second]}, source_tokens=src, ipc_signal=False
    )
    # 위치 순 (RRF) — 100 이 앞이다.
    assert [c.application_number for c in ordered] == ["100", "200"]


def test_bm25_is_deterministic_and_respects_exclude():
    src = frozenset(tokenize("방화셔터 연동 제어"))
    hits = {
        "질의 가": [
            _hit_with_abstract("300", "질의 가", "방화셔터 제어", "셔터를 제어"),
            _hit_with_abstract("100", "질의 가", "방화셔터 연동", "연동 제어"),
        ],
        "질의 나": [_hit_with_abstract("200", "질의 나", "무관한 발명", "무관")],
    }
    shuffled = {k: hits[k] for k in sorted(hits, reverse=True)}
    first = [
        c.application_number
        for c in rank_candidates_bm25(hits, source_tokens=src, ipc_signal=False)
    ]
    second = [
        c.application_number
        for c in rank_candidates_bm25(shuffled, source_tokens=src, ipc_signal=False)
    ]
    assert first == second
    without_top = rank_candidates_bm25(
        hits,
        source_tokens=src,
        exclude=frozenset({first[0]}),
        ipc_signal=False,
    )
    assert first[0] not in [c.application_number for c in without_top]


def test_search_hits_carry_abstract_from_response():
    client = KiprisClient(
        "test-key", client=object(), search_fields=("inventionTitle",)
    )

    async def fake_get(path: str, params: dict):
        return fromstring(
            "<response><header><resultCode>00</resultCode></header><body>"
            "<totalCount>7</totalCount><items><item>"
            "<applicationNumber>1020200000001</applicationNumber>"
            "<inventionTitle>방화셔터 연동제어기</inventionTitle>"
            "<astrtCont>방화셔터를 연동하여 제어하는 장치이다.</astrtCont>"
            "</item></items></body></response>"
        )

    client._get = fake_get
    hits = run(client.search("셔터 연동", rows=20))
    assert hits[0].abstract == "방화셔터를 연동하여 제어하는 장치이다."
    assert hits[0].metadata["search_total"] == "7"


def test_fielded_v2_version_string_names_the_rank_machine():
    model = ScriptedModelClient(
        [
            TechnicalExtraction(
                is_technical=True,
                technical_elements=["방화셔터 연동 제어"],
                search_queries=["방화셔터 연동 제어"],
                source_segment_ids=["seg-1"],
            )
        ]
    )
    analyzer = PatentAnalyzer(
        SpyProvider(),
        model,
        search_plan=FIELDED_V2_PLAN,
        compare_strategy="rag",
    )
    artifact = make_artifact(
        "방화셔터를 연동 제어하는 설계.",
        logical_path="/Google Drive user@example.com/docs/plan.md",
        kind=ArtifactKind.DOCUMENT_TEXT,
        analyzers=[AnalysisType.PATENT],
    )
    result = run(analyzer.analyze(artifact))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert "search_fielded_v2" in result.versions.prompt_version
    assert "patent_rank_bm25_v1" in result.versions.prompt_version


# ------------------------------------------------------------------ 정밀꼬리


def test_fielded_v3_plan_adds_judge_tail():
    plan = plan_for("fielded_v3")
    assert plan is FIELDED_V3_PLAN
    assert plan.judge_tail_to == 24
    assert plan.judge_tail_total_cap == 30
    assert plan.rows == 60  # 깊이 120 은 실측에서 잡음 — 60 유지
    # 기존 계획들은 정밀꼬리를 켜지 않는다.
    assert FIELDED_V2_PLAN.judge_tail_to == 0
    assert BASELINE_PLAN.judge_tail_to == 0


def test_judge_tail_appends_precise_title_hits_below_cap():
    """cap 밖 후보라도 정밀 제목 적중이면 판정 대상에 덧붙는다."""
    src = frozenset(tokenize("방화셔터 연동 제어"))
    hits_by_query = {}
    # cap(2)을 채울 상위 후보 둘 — 원문 어휘와 겹치는 초록.
    hits_by_query["질의 상위"] = [
        _hit_with_abstract("100", "질의 상위", "방화셔터 연동", "방화셔터를 연동 제어"),
        _hit_with_abstract("200", "질의 상위", "방화셔터 제어", "방화셔터를 제어"),
    ]
    # 어휘 겹침 없는 후보 — BM25 0. 정밀 제목 질의(전체 7건)로 걸렸다.
    precise = _hit_with_abstract("300", "정밀 질의", "무관 제목", "무관 본문")
    precise.metadata.update({"search_field": "inventionTitle", "search_total": "7"})
    # 같은 순위권의 광역 질의 적중 — 꼬리 자격 없음.
    broad = _hit_with_abstract("400", "광역 질의", "다른 제목", "다른 본문")
    broad.metadata.update({"search_field": "astrtCont", "search_total": "2000"})
    hits_by_query["정밀 질의"] = [precise]
    hits_by_query["광역 질의"] = [broad]

    selected = rank_candidates_bm25(
        hits_by_query,
        source_tokens=src,
        cap=2,
        ipc_signal=False,
        judge_tail_to=10,
        judge_tail_total_cap=30,
    )
    numbers = [c.application_number for c in selected]
    assert numbers[:2] == ["100", "200"]  # 상위는 그대로
    assert "300" in numbers  # 정밀꼬리 합류
    assert "400" not in numbers  # 광역 적중은 합류하지 않는다
    tail = next(c for c in selected if c.application_number == "300")
    assert tail.metadata.get("judge_tail") == "true"


def test_judge_tail_off_by_default():
    src = frozenset(tokenize("방화셔터"))
    precise = _hit_with_abstract("300", "질의", "무관", "무관")
    precise.metadata.update({"search_field": "inventionTitle", "search_total": "7"})
    top = _hit_with_abstract("100", "질의", "방화셔터", "방화셔터 장치")
    selected = rank_candidates_bm25(
        {"질의": [top, precise]}, source_tokens=src, cap=1, ipc_signal=False
    )
    assert [c.application_number for c in selected] == ["100"]
