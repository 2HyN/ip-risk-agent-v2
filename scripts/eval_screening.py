"""스크리닝(2단계 대조 1단계) 라이브 평가 — 인용 통과율을 잰다.

고정 풀(r62) 위에서 v3 선별(top-8+정밀꼬리)을 재현하고, 정밀 채널을
운영과 같은 프롬프트로 Gemini 에 일괄 선별시켜 본다. 지표:

* 스크린 풀에 있던 심사관 인용 중 **통과한 비율** (스크리닝 재현율)
* 문서당 평균 통과 수 (본대조 추가 비용)
* 최종 판정 도달 (선별 ∪ 생존자)

    PYTHONIOENCODING=utf-8 GCP_PROJECT_ID=... GOLDEN_DIR=... \
      .venv/Scripts/python scripts/eval_screening.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import _repo_path  # noqa: F401
from _gcloud_creds import maybe_inject

ROOT = Path(__file__).resolve().parents[1]


async def main_async() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from sweep_rerank import (
        CAP,
        bm25_scores,
        fuse_multiply,
        load_cases,
        precise_tail,
        rrf_scores,
    )
    from ip_risk_agent.intelligence.gemini.client import (
        GoogleGenAIClient,
        PromptLibrary,
    )
    from ip_risk_agent.intelligence.gemini.schemas import PatentScreening
    from ip_risk_agent.intelligence.patent.search_strategy import FIELDED_V5_PLAN

    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project:
        raise SystemExit("GCP_PROJECT_ID 필요")
    model = GoogleGenAIClient(
        os.environ.get("GEMINI_MODEL_ID") or os.environ.get(
            "GEMINI_MODEL", "gemini-3.6-flash"
        ),
        vertex_config=maybe_inject({"vertexai": True, "project": project, "location": "global"}),
    )
    prompt = PromptLibrary().get("patent_screen_v1")
    plan = FIELDED_V5_PLAN

    cases = load_cases(rows=62, queries_prefix="queriesv4")
    total = sum(len(c["cited"]) for c in cases)

    def min_total(cand):
        totals = [h["total"] for h in cand["hits"] if h["total"] is not None]
        return min(totals) if totals else None

    base_hits = final_hits = pool_cited = passed_cited = 0
    pass_sizes = []
    for case in cases:
        scores = fuse_multiply(bm25_scores(case), rrf_scores(case))
        selection = set(precise_tail(case, scores))
        base_hits += len(case["cited"] & selection)
        # 정밀 채널 (선별 밖, ≤ screen_total_cap) — (최소총계, 출원번호) 순
        channel = [
            (mt, appno)
            for appno, cand in case["candidates"].items()
            if appno not in selection
            and (mt := min_total(cand)) is not None
            and mt <= plan.screen_total_cap
        ]
        channel.sort()
        channel = channel[: plan.screen_pool_limit]
        pool = [appno for _, appno in channel]
        cited_in_pool = case["cited"] & set(pool)
        pool_cited += len(cited_in_pool)
        survivors: set[str] = set()
        if pool:
            listing = "\n".join(
                f"[{i + 1}] {case['candidates'][a]['title']}"
                + (
                    f" — {case['candidates'][a]['abstract'][:300]}"
                    if case["candidates"][a]["abstract"]
                    else ""
                )
                for i, a in enumerate(pool)
            )
            rendered = prompt.render(
                segments=f"[seg-1]\n{case['source_abstract']}",
                candidates=listing,
                max_pass=plan.screen_max_pass,
            )
            try:
                screening = await model.generate(rendered, PatentScreening)
                seen = set()
                for index in screening.related_indexes:
                    if (
                        isinstance(index, int)
                        and 1 <= index <= len(pool)
                        and index not in seen
                    ):
                        seen.add(index)
                        survivors.add(pool[index - 1])
                        if len(survivors) >= plan.screen_max_pass:
                            break
            except Exception as exc:  # noqa: BLE001
                print(f"  {case['number']}: 스크리닝 실패 {type(exc).__name__}")
        passed_cited += len(cited_in_pool & survivors)
        pass_sizes.append(len(survivors))
        final_hits += len(case["cited"] & (selection | survivors))
        print(
            f"  {case['number']}: 풀 {len(pool)}건 → 통과 {len(survivors)}건"
            f" · 인용 풀내 {len(cited_in_pool)} → 통과 {len(cited_in_pool & survivors)}"
        )

    print(f"\n출원 {len(cases)} · 인용 {total}")
    print(f"  선별만(v3 구성):      판정 도달 {base_hits}/{total}")
    print(
        f"  스크리닝 재현율:      {passed_cited}/{pool_cited}"
        f" ({passed_cited / pool_cited:.0%})" if pool_cited else "  스크린 풀에 인용 없음"
    )
    print(
        f"  + 스크리닝 생존자:    판정 도달 {final_hits}/{total}"
        f" ({final_hits / total:.0%}) · 문서당 통과 평균 {sum(pass_sizes) / len(pass_sizes):.1f}건"
    )
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
