"""확장 골든셋(v2)용 무작위 음성 쌍을 만든다 — 정밀도·오탐율 측정 입력.

기존 build_negative_pairs.py 와 같은 프로토콜(seed 42, 출원당 2쌍, 원문 있는
인용 풀에서 해당 출원의 확정 인용을 제외하고 무작위 추출)이되 두 가지를 고친다:
1. 확정 인용 제외를 출원 단위 합집합으로 계산한다 — 기존 dict(zip(...)) 은
   통지서(sendNumber)가 여러 개인 출원에서 마지막 행의 인용만 제외해서
   진짜 인용이 음성 쌍에 섞일 수 있었다 (v2 재료엔 중복 출원 26행 존재).
2. pandas 의존을 없앴다 (표준 라이브러리만).

주의: 이 음성은 여전히 '약한 음성'(무작위)이다. IPC-서로소 안전 음성은
PATENT_NEGATIVE_PAIRS_HANDOFF.md §5 대로 advanced_rag 쪽 소관.

사용:
    python scripts/build_negative_pairs_v2.py [--dir samples/patent] [--n-per-app 2] [--seed 42]
"""
from __future__ import annotations

import argparse
import ast
import csv
import random
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dir", default="samples/patent")
    parser.add_argument("--n-per-app", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None, help="기본: <dir>/negative_pairs_v2.csv")
    args = parser.parse_args()
    base = Path(args.dir)
    rng = random.Random(args.seed)

    claims_map = {r["applicationNumber"]: r["claims"] for r in load(base / "gold_target_claims_all.csv")}
    fulltext_map = {
        r["식별자"]: r["원문텍스트"]
        for r in load(base / "gold_cited_fulltext_all.csv")
        if (r["원문텍스트"] or "").strip()
    }
    all_ids = sorted(fulltext_map)  # 순서 고정 → seed 만으로 재현 가능

    # 출원 단위 확정 인용 합집합 (통지서 여러 개여도 전부 제외)
    true_citations: dict[str, set[str]] = {}
    domain_map: dict[str, str] = {}
    for r in load(base / "gold_reject_decisions_all.csv"):
        app = r["applicationNumber"]
        try:
            ids = {c["식별자"] for c in ast.literal_eval(r["kr_citations"]) if "식별자" in c}
        except Exception:
            ids = set()
        true_citations.setdefault(app, set()).update(ids)
        if r.get("domain"):
            domain_map[app] = r["domain"]

    rows = []
    for app_no in sorted(claims_map):
        cited_ids = true_citations.get(app_no, set())
        candidates = [i for i in all_ids if i not in cited_ids]
        if not candidates:
            continue
        for cid in rng.sample(candidates, min(args.n_per_app, len(candidates))):
            rows.append({
                "applicationNumber": app_no,
                "target_claims": claims_map[app_no],
                "cited_식별자": cid,
                "cited_fulltext": fulltext_map[cid],
                "label": "negative",
                "domain": domain_map.get(app_no, ""),
            })

    out = Path(args.out or base / "negative_pairs_v2.csv")
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"negative pairs: {len(rows)} (출원 {len({r['applicationNumber'] for r in rows})}, seed={args.seed}, n_per_app={args.n_per_app})")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
