"""골든셋 재료 3종 CSV 를 PATENT_NEGATIVE_PAIRS_HANDOFF.md §4 체크리스트로 검증한다.

체크 항목 (advanced_rag docs/PATENT_NEGATIVE_PAIRS_HANDOFF.md §4):
1. CSV 3개가 UTF-8 로 읽히고 컬럼명이 §1 과 일치한다
2. A 의 claims 와 C 의 kr_citations 가 ast.literal_eval 로 파싱된다
3. C 의 모든 식별자 가 B 에 존재한다 (전문 누락 0)
4. B 의 원문텍스트 90% 이상에서 (21) 과 (51) 줄이 검출된다
5. 새 출원이 기존 출원과 중복되지 않는다 (--baseline 지정 시 기존 대비 순증만 집계)

사용:
    python scripts/validate_gold_materials.py [--dir samples/patent] [--baseline-ref cost-logging]
"""
from __future__ import annotations

import argparse
import ast
import csv
import re

csv.field_size_limit(10_000_000)
import subprocess
import sys
from collections import Counter
from pathlib import Path

FILES = {
    "A": "gold_target_claims_all.csv",
    "B": "gold_cited_fulltext_all.csv",
    "C": "gold_reject_decisions_all.csv",
}
REQUIRED_COLS = {
    "A": {"applicationNumber", "claims"},
    "B": {"식별자", "원문텍스트"},
    "C": {"applicationNumber", "kr_citations"},
}


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def check(label: str, ok: bool, detail: str) -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label} — {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dir", default="samples/patent")
    parser.add_argument(
        "--baseline-ref", default=None,
        help="기존 재료가 커밋된 git ref (예: cost-logging). 지정하면 기존 행 보존·순증을 검증",
    )
    args = parser.parse_args()
    base = Path(args.dir)

    ok_all = True
    data: dict[str, list[dict]] = {}

    # 1. 읽기 + 컬럼
    for key, name in FILES.items():
        rows = load(base / name)
        data[key] = rows
        cols = set(rows[0].keys()) if rows else set()
        ok_all &= check(
            f"1. {name} 컬럼", REQUIRED_COLS[key] <= cols,
            f"{len(rows)}행, 필수 {sorted(REQUIRED_COLS[key])} ⊆ {sorted(cols)}",
        )

    # 2. 파싱
    bad_claims = []
    for r in data["A"]:
        try:
            v = ast.literal_eval(r["claims"])
            assert isinstance(v, list) and v
        except Exception:
            bad_claims.append(r["applicationNumber"])
    ok_all &= check("2a. A.claims literal_eval", not bad_claims, f"실패 {len(bad_claims)}건 {bad_claims[:5]}")

    bad_cit, pair_ids = [], []
    for r in data["C"]:
        try:
            v = ast.literal_eval(r["kr_citations"])
            assert isinstance(v, list)
            pair_ids += [(r["applicationNumber"], d["식별자"]) for d in v]
        except Exception:
            bad_cit.append(r["applicationNumber"])
    ok_all &= check("2b. C.kr_citations literal_eval", not bad_cit, f"실패 {len(bad_cit)}건 {bad_cit[:5]}")

    # 3. C→B 존재
    b_ids = {r["식별자"] for r in data["B"]}
    missing = sorted({i for _, i in pair_ids if i not in b_ids})
    ok_all &= check("3. C.식별자 ⊆ B", not missing, f"누락 {len(missing)}건 {missing[:5]}")

    # 3b. (참고) B 행은 있으나 원문이 빈 경우 — 재현율 셋에서 제외되는 쌍
    empty_ids = {r["식별자"] for r in data["B"] if not (r["원문텍스트"] or "").strip()}
    affected = sum(1 for _, i in pair_ids if i in empty_ids)
    kinds = Counter(i.split()[0] for i in empty_ids)
    print(f"[INFO] 3b. 원문 빈 B 행 {len(empty_ids)}건 ({dict(kinds)}) — 영향 쌍 {affected}건은 재현율 셋에서 제외")

    # 4. (21)/(51) 검출 — 원문이 있는 행 기준과 전체 기준을 함께 보고
    texts = [(r["원문텍스트"] or "") for r in data["B"]]
    nonempty = [t for t in texts if t.strip()]
    hit = sum(1 for t in nonempty if re.search(r"\(21\)", t) and re.search(r"\(51\)", t))
    ratio_all = hit / len(texts) if texts else 0
    ratio_ne = hit / len(nonempty) if nonempty else 0
    ok_all &= check(
        "4. (21)·(51) 검출 ≥90%", ratio_ne >= 0.9,
        f"원문 있는 행 기준 {ratio_ne:.1%} ({hit}/{len(nonempty)}), 전체 행 기준 {ratio_all:.1%}",
    )

    # 5. 중복
    dup_a = [k for k, c in Counter(r["applicationNumber"] for r in data["A"]).items() if c > 1]
    dup_b = [k for k, c in Counter(r["식별자"] for r in data["B"]).items() if c > 1]
    ok_all &= check("5a. A 출원 중복 없음", not dup_a, f"중복 {len(dup_a)}건 {dup_a[:5]}")
    ok_all &= check("5b. B 식별자 중복 없음", not dup_b, f"중복 {len(dup_b)}건 {dup_b[:5]}")

    # 5c. 기존 대비 (baseline ref 가 주어지면): 기존 행 보존 + 순증 집계
    if args.baseline_ref:
        try:
            raw = subprocess.run(
                ["git", "show", f"{args.baseline_ref}:{base.as_posix()}/{FILES['A']}"],
                capture_output=True, check=True,
            ).stdout.decode("utf-8-sig")
            old_rows = list(csv.DictReader(raw.splitlines()))
            old_map = {r["applicationNumber"]: r["claims"] for r in old_rows}
            new_map = {r["applicationNumber"]: r["claims"] for r in data["A"]}
            lost = [k for k in old_map if k not in new_map]
            changed = [k for k in old_map if k in new_map and old_map[k] != new_map[k]]
            added = len(new_map) - (len(old_map) - len(lost))
            ok_all &= check(
                f"5c. 기존({args.baseline_ref}) 행 보존", not lost and not changed,
                f"기존 {len(old_map)} → 유실 {len(lost)}, 변경 {len(changed)}, 순증 +{added} (총 {len(new_map)})",
            )
        except subprocess.CalledProcessError:
            print(f"[WARN] 5c. baseline ref {args.baseline_ref} 에서 기존 파일을 읽지 못함 — 건너뜀")

    uniq_pairs = len(set(pair_ids))
    usable = len({p for p in set(pair_ids) if p[1] not in empty_ids and p[0] in {r["applicationNumber"] for r in data["A"]}})
    print(f"\n요약: 출원 {len(data['A'])} · 인용 전문 {len(data['B'])} (빈 원문 {len(empty_ids)}) · "
          f"(출원,인용) 유일 쌍 {uniq_pairs} · 재현율 셋 사용 가능 쌍 {usable}")
    print("체크리스트:", "통과" if ok_all else "실패")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
