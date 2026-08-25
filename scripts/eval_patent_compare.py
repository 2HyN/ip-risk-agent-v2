"""KIPO 거절결정문 기반 gold set으로 PatentComparison 재현율을 측정한다.

문서-특허 겹침 판정(patent_compare_v2)은 정답이 없어 지금까지 직접 검증이
안 됐다. 실제 심사관이 신규성(특허법 제29조제1항)으로 확정한 인용 쌍 163개를
대리 정답 삼아, 우리 PatentComparison이 알려진 겹침을 놓치지 않는지(재현율)를 잰다.
"""
from __future__ import annotations

import _repo_path  # noqa: F401 -- 저장소 코드를 먼저 경로에 올린다

import argparse
import ast
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient, PromptLibrary
from ip_risk_agent.intelligence.gemini.schemas import PatentComparison

PROMPT_NAME = "patent_compare_v2"
DEFAULT_FULLTEXT_CHARS = 8000

# 확장 골든셋(verification_pairs_v2)의 일부 행이 csv 기본 필드 한도(131072자)를 넘는다
csv.field_size_limit(10_000_000)


def load_pairs(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--in", dest="in_path", default="samples/patent/verification_pairs_163.csv")
    parser.add_argument("--out", default="eval-results/patent_compare_recall.csv")
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL_ID", "gemini-3.6-flash"))
    parser.add_argument("--limit", type=int, default=None, help="테스트용으로 앞에서 N개만 실행")
    parser.add_argument("--fulltext-chars", type=int, default=DEFAULT_FULLTEXT_CHARS)
    args = parser.parse_args()

    if "GEMINI_API_KEY" not in os.environ:
        print("GEMINI_API_KEY 없음")
        return 1

    client = GoogleGenAIClient(args.model, api_key=os.environ["GEMINI_API_KEY"])
    prompt = PromptLibrary().get(PROMPT_NAME)

    pairs = load_pairs(Path(args.in_path))
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"대상: {len(pairs)}쌍 (model={args.model})")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for i, row in enumerate(pairs):
        claims = ast.literal_eval(row["target_claims"])
        segments = "[seg-1]\n" + "\n".join(claims)
        fulltext = row["cited_fulltext"][: args.fulltext_chars]
        evidence = f"[patent-1] 식별자 {row['cited_식별자']}\n원문:\n{fulltext}"

        try:
            comparison = await client.generate(
                prompt.render(segments=segments, patent_evidence=evidence),
                PatentComparison,
            )
        except Exception as exc:  # noqa: BLE001 - 평가는 계속한다
            print(f"  [{i+1}/{len(pairs)}] 실패 ({row['applicationNumber']}): {type(exc).__name__}")
            results.append({
                "applicationNumber": row["applicationNumber"], "cited_식별자": row["cited_식별자"],
                "hit": False, "error": str(exc),
                "matched_elements": "", "distinct_elements": "", "review_caveats": "",
            })
            continue

        hit = len(comparison.matched_elements) > 0
        print(
            f"  [{i+1}/{len(pairs)}] {row['applicationNumber']} vs {row['cited_식별자']}"
            f" → hit={hit} (matched={len(comparison.matched_elements)})"
        )
        results.append({
            "applicationNumber": row["applicationNumber"], "cited_식별자": row["cited_식별자"],
            "hit": hit, "error": "",
            "matched_elements": json.dumps(comparison.matched_elements, ensure_ascii=False, default=str),
            "distinct_elements": json.dumps(comparison.distinct_elements, ensure_ascii=False, default=str),
            "review_caveats": json.dumps(comparison.review_caveats, ensure_ascii=False, default=str),
        })

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    hits = sum(1 for r in results if r["hit"])
    recall = hits / len(results) if results else 0.0
    print(f"\n재현율: {recall:.1%} ({hits}/{len(results)})")
    print(f"결과 저장: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
