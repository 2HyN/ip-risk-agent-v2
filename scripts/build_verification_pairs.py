"""재료 CSV 3종에서 PatentComparison 재현율 검증 쌍을 결정적으로 만든다.

구성 (verification_pairs_157/163 과 같은 결합):
    gold_reject_decisions_all.kr_citations 를 행으로 펼친 뒤
    gold_target_claims_all 에서 target_claims,
    gold_cited_fulltext_all 에서 cited_fulltext 를 붙인다.

출력 2종:
    verification_pairs_v2_all.csv — 펼친 전 행 (원문 빈 쌍 포함; 보충 수집 대상 추적용)
    verification_pairs_v2.csv     — 원문이 있는 행만 (재현율 평가 입력)

기존 163→157 과 달리 별도 수기 필터 없이 재료에서 전량 재구성한다
(has_29_1 컬럼은 확정 인용 행에서도 False 로 남아 있는 미완성 컬럼이라 쓰지 않는다).
같은 (출원,인용) 쌍이 통지서(sendNumber)마다 반복될 수 있어 --dedupe 를 주면
쌍 단위로 병합한다 (advanced_rag 프로토콜의 '유일 쌍' 방식).

사용:
    python scripts/build_verification_pairs.py [--dir samples/patent] [--dedupe]
"""
from __future__ import annotations

import argparse
import ast
import csv
import sys
from pathlib import Path

csv.field_size_limit(10_000_000)


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dir", default="samples/patent")
    parser.add_argument("--dedupe", action="store_true", help="(출원,인용) 유일 쌍으로 병합 (첫 통지서 기준)")
    parser.add_argument("--out-all", default=None, help="기본: <dir>/verification_pairs_v2_all.csv")
    parser.add_argument("--out", default=None, help="기본: <dir>/verification_pairs_v2.csv")
    args = parser.parse_args()
    base = Path(args.dir)

    claims_map = {r["applicationNumber"]: r["claims"] for r in load(base / "gold_target_claims_all.csv")}
    fulltext_map = {r["식별자"]: (r["원문텍스트"] or "") for r in load(base / "gold_cited_fulltext_all.csv")}
    decisions = load(base / "gold_reject_decisions_all.csv")

    rows, missing_claims, missing_fulltext = [], set(), set()
    for dec in decisions:
        app = dec["applicationNumber"]
        if app not in claims_map:
            missing_claims.add(app)
            continue
        for cit in ast.literal_eval(dec["kr_citations"]):
            ident = cit["식별자"]
            if ident not in fulltext_map:
                missing_fulltext.add(ident)
                continue
            rows.append({
                "applicationNumber": app,
                "sendNumber": dec["sendNumber"],
                "target_claims": claims_map[app],
                "cited_식별자": ident,
                "cited_fulltext": fulltext_map[ident],
                "domain": dec.get("domain") or "",
            })

    if args.dedupe:
        seen, deduped = set(), []
        for r in rows:
            key = (r["applicationNumber"], r["cited_식별자"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        rows = deduped

    usable = [r for r in rows if r["cited_fulltext"].strip()]
    out_all = Path(args.out_all or base / "verification_pairs_v2_all.csv")
    out = Path(args.out or base / "verification_pairs_v2.csv")
    fields = ["applicationNumber", "sendNumber", "target_claims", "cited_식별자", "cited_fulltext", "domain"]
    for path, subset in ((out_all, rows), (out, usable)):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(subset)

    n_apps = len({r["applicationNumber"] for r in usable})
    n_pairs = len({(r["applicationNumber"], r["cited_식별자"]) for r in usable})
    print(f"전체 행 {len(rows)} → 원문 있는 행 {len(usable)} (출원 {n_apps}, 유일 쌍 {n_pairs})")
    if missing_claims:
        print(f"경고: 청구항 없는 출원 {len(missing_claims)}건 제외 {sorted(missing_claims)[:5]}")
    if missing_fulltext:
        print(f"경고: B 에 없는 식별자 {len(missing_fulltext)}건 제외 {sorted(missing_fulltext)[:5]}")
    print(f"저장: {out_all} / {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
