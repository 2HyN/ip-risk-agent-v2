"""검색 전략(확장·완화·RRF·버킷) 회귀 테스트.

베이스라인 보존이 1급 요구다 — 계획을 넣지 않은 분석기가 현행과 같은 인자로
검색하고 같은 기록 문자열을 내는 것을 스파이로 고정한다 (계획 문서 §3, §6-1).
"""

from __future__ import annotations

import asyncio

import pytest

from ip_risk_agent.intelligence.common.errors import (
    FailureCategory,
    ProviderFailureError,
)
from ip_risk_agent.intelligence.patent.candidate_rank import (
    rank_candidates,
    rank_candidates_rrf,
)
from ip_risk_agent.intelligence.patent.extraction import clamp_queries
from ip_risk_agent.intelligence.patent.kipris import PatentSearchHit
from ip_risk_agent.intelligence.patent.query_builder import run_searches
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket
from ip_risk_agent.intelligence.patent.search_strategy import (
    BASELINE_PLAN,
    EXPANDED_V1_PLAN,
    plan_for,
    require_compare_strategy,
)

from test_license import run


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
