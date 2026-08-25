"""순위층 스위프 — 캐시된 풀 위에서 선별 손잡이만 바꿔 잰다.

## 왜 이 층인가

샘플 실측(출원 10 · 인용 16, fielded_v3)의 손실 분해:

    인용 16건 → 풀 진입 6건(38%) → 판정 대상 2건(12.5%)

**검색이 데려온 것의 67%를 순위층이 잘라낸다.** E2-4 에서 BM25 가 풀의 53%
를 회수했던 것보다 나쁘다. 그리고 이 층에는 **낡은 교정**이 하나 박혀 있다 —
정밀꼬리의 ``judge_tail_total_cap=30`` 은 깨진 클라이언트(공백 조인)로 모은
고정 풀에서 정해졌는데, `*` AND 수정이 결과집합 크기를 바꿨다 (셔터 연동 제어
초록 18 → 122). 필터가 지금 무엇을 통과시키는지가 측정 당시와 다르다.

## 왜 공짜인가

``evaluate_search_recall.py`` 의 검색 응답 캐시를 그대로 읽는다. 질의도
캐시돼 있다. 그래서 KIPRIS·Gemini 호출이 **0회**이고, 변형 수십 개를 즉시
잰다 — 고정 풀 ablation 과 같은 성질을 라이브 수집 위에 얹은 것이다.

**전제**: 대상 전략으로 ``evaluate_search_recall.py`` 를 한 번 돌려 캐시를
채워 두어야 한다. 캐시가 비면 이 스크립트는 그 출원을 건너뛴다 (조용히
호출하지 않는다 — 측정이 몰래 비싸지는 것을 막는다).

    PYTHONIOENCODING=utf-8 GOLDEN_DIR=... \
      python scripts/sweep_search_rank.py --search-strategy fielded_v3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

import evaluate_search_recall as sr
from ip_risk_agent.intelligence.patent.ephemeral_index import tokenize
from ip_risk_agent.intelligence.patent.extraction import expand_queries
from ip_risk_agent.intelligence.patent.query_builder import run_searches
from ip_risk_agent.intelligence.patent.search_strategy import plan_for


class OfflineOnly:
    """캐시에 있는 것만 돌려준다. 없으면 표식을 남기고 빈 결과."""

    def __init__(self, fields, cache: Path) -> None:
        self._inner = sr.CachedSearch(None, fields, cache)
        self.missing = 0

    async def search(self, query: str, *, rows: int = 5):
        path = self._inner._path(query, rows)
        if not path.exists():
            self.missing += 1
            return []
        return await self._inner.search(query, rows=rows)


async def _pool_for(record, plan, provider):
    """한 출원의 검색 결과를 캐시에서 되살린다."""
    number = record["application_number"]
    queries_path = sr.OUT_ROOT / plan.name / f"queries-{number}.json"
    if not queries_path.exists():
        return None
    originals = json.loads(queries_path.read_text(encoding="utf-8"))
    executed = (
        expand_queries(originals, cap=plan.expansion_cap)
        if plan.expand_queries
        else originals
    )
    if not executed:
        return None
    outcome = await run_searches(
        provider,
        executed,
        rows=plan.rows,
        relax_zero_hits=plan.relax_zero_hits,
        stage_deadline_seconds=None,
    )
    cutoff = sr._application_date_of(number)
    if cutoff:
        from ip_risk_agent.intelligence.patent.analyzer import _drop_future_hits

        _drop_future_hits(outcome.hits_by_query, cutoff)
    if not outcome.hits_by_query:
        return None
    return originals, executed, outcome


def _variants(plan):
    """잴 변형들. 이름은 무엇을 바꿨는지 그대로 읽히게 둔다."""
    rows = [("운영 현행", plan)]
    # ── 정밀꼬리 임계값 — `*` 수정으로 결과집합이 커졌으니 상한도 커져야 하는가
    for total_cap in (10, 30, 60, 120, 300, 1000):
        rows.append(
            (f"tail총량<={total_cap}", replace(plan, judge_tail_total_cap=total_cap))
        )
    # ── 정밀꼬리 깊이
    for tail_to in (0, 16, 24, 40, 60):
        rows.append((f"tail깊이{tail_to}", replace(plan, judge_tail_to=tail_to)))
    # ── cap 자체
    for cap in (6, 8, 12, 16, 24):
        rows.append((f"cap{cap}", replace(plan, compare_cap=cap)))
    # ── 순위 기계 교체
    rows.append(("RRF(BM25끔)", replace(plan, use_bm25=False, use_rrf=True)))
    rows.append(("적중수·위치", replace(plan, use_bm25=False, use_rrf=False)))
    # ── 조합: 임계값 완화 + 깊이 확대
    rows.append(
        ("tail깊이40+총량300", replace(plan, judge_tail_to=40, judge_tail_total_cap=300))
    )
    rows.append(
        ("tail깊이60+총량1000", replace(plan, judge_tail_to=60, judge_tail_total_cap=1000))
    )
    return rows


async def run(args) -> int:
    plan = plan_for(args.search_strategy)
    records = [
        json.loads(line)
        for line in (sr.GOLDEN / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [r for r in records if r.get("examiner_cited")][: args.limit or None]
    resolved = sr._resolved_citations()

    provider = OfflineOnly(plan.search_fields, sr.SEARCH_CACHE)
    pools = []
    for record in records:
        number = record["application_number"]
        abstract = sr._abstract_of(number)
        if not abstract:
            continue
        found = await _pool_for(record, plan, provider)
        if found is None:
            continue
        originals, executed, outcome = found
        cited = [resolved.get(str(c), str(c)) for c in record["examiner_cited"]]
        cited = [c for c in cited if c != number]
        pools.append((number, abstract, originals, executed, outcome, cited))

    if not pools:
        raise SystemExit(
            f"{plan.name} 캐시가 비었다 — 먼저 evaluate_search_recall.py 를 돌려라"
        )
    citations = sum(len(row[5]) for row in pools)
    print(f"{plan.name}: 출원 {len(pools)}건 · 인용 {citations}건 (호출 0회)")
    if provider.missing:
        print(f"  캐시 미적중 질의 {provider.missing}개 — 그만큼 풀이 작다")

    # 풀 천장 — 순위를 아무리 잘해도 못 넘는 선.
    ceiling = sum(
        1
        for number, _, _, _, outcome, cited in pools
        for citation in cited
        if citation
        in {
            hit.application_number
            for hits in outcome.hits_by_query.values()
            for hit in hits
        }
    )
    print(f"  풀 천장 {ceiling}/{citations}  <- 순위층의 상한\n")

    print(f"{'변형':<22} {'판정적중':>9} {'회수율':>7} {'판정대상/문서':>13}")
    print("-" * 56)
    results = []
    for name, variant in _variants(plan):
        hit = 0
        judged_sizes = []
        for number, abstract, originals, executed, outcome, cited in pools:
            selected = sr._select(
                variant, outcome, originals, executed, abstract, frozenset({number})
            )
            judged = {c.application_number for c in selected}
            judged_sizes.append(len(judged))
            hit += sum(1 for c in cited if c in judged)
        share = hit / ceiling * 100 if ceiling else 0.0
        mean_judged = sum(judged_sizes) / len(judged_sizes)
        results.append((name, hit, share, mean_judged))
        print(f"{name:<22} {hit:>4}/{citations:<4} {share:>6.0f}% {mean_judged:>13.1f}")

    best = max(results, key=lambda r: (r[1], -r[3]))
    print(
        f"\n최고: {best[0]} — {best[1]}/{citations}"
        f" (풀의 {best[2]:.0f}% 회수 · 문서당 판정 {best[3]:.1f}건)"
    )
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-strategy", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
