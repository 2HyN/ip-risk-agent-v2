"""재현율(양성) + 오탐(음성) 결과 CSV 두 개를 합쳐 재현율·정밀도·오탐율·F1 을 낸다.

eval_patent_compare.py 를 두 번 돌린 결과를 입력으로 받는다:
    양성: --in samples/patent/verification_pairs_v2.csv → hit=True 가 TP
    음성: --in samples/patent/negative_pairs_v2.csv     → hit=True 가 FP

사용:
    python scripts/summarize_precision_recall.py \
        --positive eval-results/patent_compare_recall_v2.csv \
        --negative eval-results/patent_compare_fp_v2.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)


def load_hits(paths: list[str]) -> tuple[int, int, int]:
    """여러 결과 CSV 를 이어 붙여 행 단위로 집계한다 (구간이 겹치지 않게 --offset/--limit 로 나눠 돌린 결과용)."""
    rows: list[dict] = []
    for p in paths:
        with Path(p).open(encoding="utf-8-sig") as f:
            rows.extend(csv.DictReader(f))
    errors = sum(1 for r in rows if (r.get("error") or "").strip())
    hits = sum(1 for r in rows if r["hit"] in ("True", "true", "1"))
    return hits, len(rows), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--positive", required=True, nargs="+", help="양성(검증 쌍) 결과 CSV — 여러 개면 이어 붙임")
    parser.add_argument("--negative", required=True, nargs="+", help="음성 쌍 결과 CSV — 여러 개면 이어 붙임")
    args = parser.parse_args()

    tp, n_pos, err_pos = load_hits(args.positive)
    fp, n_neg, err_neg = load_hits(args.negative)
    fn = n_pos - tp
    tn = n_neg - fp

    recall = tp / n_pos if n_pos else 0.0
    fpr = fp / n_neg if n_neg else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"양성 {n_pos}쌍 (오류 {err_pos}) · 음성 {n_neg}쌍 (오류 {err_neg})")
    print(f"TP {tp} / FN {fn} / FP {fp} / TN {tn}")
    print(f"재현율  {recall:.1%} ({tp}/{n_pos})")
    print(f"정밀도  {precision:.1%} ({tp}/{tp + fp})")
    print(f"오탐율  {fpr:.1%} ({fp}/{n_neg})")
    print(f"F1      {f1:.3f}")
    print("\n참고 기준선(기존 157/142쌍, 커밋 0486d1d): 재현율 92.4% · 정밀도 75.1% · 오탐율 33.8%")
    if err_pos or err_neg:
        print("주의: error 행은 hit=False 로 집계됨 — 오류가 많으면 재실행 후 다시 집계할 것")
    return 0


if __name__ == "__main__":
    sys.exit(main())
