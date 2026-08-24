"""비용 집계 — ``cost_measure.py`` 가 남긴 JSONL 을 비용 표로 만든다.

    python scripts/cost_report.py cost-log.jsonl
    python scripts/cost_report.py cost-log.jsonl --input-price 0.30 --output-price 2.50

단가는 100만 토큰당 USD 다. 값은 공식 가격표(https://ai.google.dev/pricing)에서
확인해 넣는다 — 여기 박아 두면 가격 개정 때 조용히 낡으므로 기본값을 두지 않는다.
단가 없이 돌리면 토큰·호출 수까지만 집계한다.

같은 파일에 모델을 바꿔 여러 번 측정해도 된다. ``run_model`` 별로 나눠 집계하므로
티어링 비교표가 그대로 나온다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

#: KIPRIS 무료 등급 월 한도. 소비율 표시에 쓴다 (2차 문서 §11 실측 기준).
KIPRIS_FREE_MONTHLY_LIMIT = 1000


def _load(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and "event" in payload:
            events.append(payload)
    return events


def _fmt(n: float) -> str:
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("log", help="cost_measure.py 가 만든 JSONL 파일")
    parser.add_argument("--input-price", type=float, default=None,
                        help="Gemini 입력 단가 (USD / 1M tokens)")
    parser.add_argument("--output-price", type=float, default=None,
                        help="Gemini 출력 단가 (USD / 1M tokens)")
    args = parser.parse_args()

    events = _load(Path(args.log))
    if not events:
        print("이벤트가 없습니다. cost_measure.py 를 먼저 실행하세요.")
        return 1

    # ---------------------------------------------------------- Gemini 토큰
    # (모델, task) 별 합계. 모델별로 나뉘므로 티어링 비교가 이 표에서 끝난다.
    gemini: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "prompt": 0, "output": 0, "cached": 0}
    )
    for e in events:
        if e["event"] != "gemini_usage":
            continue
        row = gemini[(str(e.get("model_id")), str(e.get("task")))]
        row["calls"] += 1
        row["prompt"] += int(e.get("prompt_tokens", 0))
        row["output"] += int(e.get("output_tokens", 0))
        row["cached"] += int(e.get("cached_tokens", 0))

    print("## Gemini 토큰 사용량 (모델 × 작업)\n")
    print("| model | task | calls | prompt tok | output tok | cached tok |"
          + (" cost (USD) |" if args.input_price and args.output_price else ""))
    print("|---|---|---|---|---|---|" + ("---|" if args.input_price and args.output_price else ""))
    total_cost = 0.0
    for (model, task), row in sorted(gemini.items()):
        line = (f"| {model} | {task} | {row['calls']} | {_fmt(row['prompt'])} "
                f"| {_fmt(row['output'])} | {_fmt(row['cached'])} |")
        if args.input_price and args.output_price:
            cost = (row["prompt"] * args.input_price + row["output"] * args.output_price) / 1e6
            total_cost += cost
            line += f" {cost:.6f} |"
        print(line)
    if args.input_price and args.output_price:
        print(f"\nGemini 합계 비용: **${total_cost:.6f}**")
    else:
        print("\n(단가 미지정 — --input-price/--output-price 를 주면 비용까지 계산)")

    # ---------------------------------------------------------- KIPRIS 호출
    kipris: dict[str, dict[bool, int]] = defaultdict(lambda: {True: 0, False: 0})
    for e in events:
        if e["event"] == "kipris_call":
            kipris[str(e.get("operation"))][bool(e.get("cached"))] += 1
    if kipris:
        print("\n## KIPRIS 호출 (캐시 적중 = 실호출 회피)\n")
        print("| operation | 실호출 | 캐시 적중 | 적중률 |")
        print("|---|---|---|---|")
        live_total = 0
        for op, row in sorted(kipris.items()):
            live, hit = row[False], row[True]
            live_total += live
            rate = hit / (live + hit) * 100 if (live + hit) else 0.0
            print(f"| {op} | {live} | {hit} | {rate:.0f}% |")
        print(f"\n실호출 합계 {live_total}회 — 무료 한도 대비 "
              f"{live_total / KIPRIS_FREE_MONTHLY_LIMIT * 100:.1f}% "
              f"(월 {KIPRIS_FREE_MONTHLY_LIMIT}회 기준)")

    # ------------------------------------------------------ 레지스트리 호출
    registry: dict[str, int] = defaultdict(int)
    for e in events:
        if e["event"] == "registry_call":
            registry[str(e.get("provider"))] += 1
    if registry:
        print("\n## 레지스트리 호출 (무료·캐시 없음 — 호출 수만 관리)\n")
        print("| provider | calls |")
        print("|---|---|")
        for provider, calls in sorted(registry.items()):
            print(f"| {provider} | {calls} |")

    # ------------------------------------------------------ RAG 조항 검색
    clause = {True: 0, False: 0}
    for e in events:
        if e["event"] == "rag_clause_search":
            clause[bool(e.get("cached"))] += 1
    if clause[True] or clause[False]:
        total = clause[True] + clause[False]
        print("\n## RAG 조항 검색\n")
        print(f"실호출 {clause[False]}회 · 캐시 적중 {clause[True]}회 "
              f"(적중률 {clause[True] / total * 100:.0f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
