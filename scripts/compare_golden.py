"""평가 조건 간 짝비교 — 같은 출원끼리만 비교한다.

``summarize_golden.py`` 는 폴더 하나를 집계한다. 그런데 조건마다 평가한 표본이
다르면 (before 는 층화 30건, 개선판은 인용 있는 건 순서대로) 합계 비교는
표본 차이에 교란된다. 여기서는 **모든 조건에 다 있는 출원**만 골라 짝으로
비교한다 — recall 과 건별 최고 강도가 조건 간에 어떻게 움직였는지.

    python scripts/compare_golden.py eval eval-improved eval-improved-expand
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 골든셋이 저장소 밖(팀 공유 폴더)에 있으면 GOLDEN_DIR 로 가리킨다.
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))


def _load(dirname: str) -> dict[str, dict]:
    records = {}
    for path in (GOLDEN / dirname).glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        records[record["application_number"]] = record
    return records


def _top_strength(record: dict) -> float:
    strengths = [
        float(c["strength"]) for c in record["candidates"] if c["strength"]
    ]
    return max(strengths) if strengths else 0.0


def main() -> None:
    dirnames = sys.argv[1:] or ["eval", "eval-improved"]
    loaded = {name: _load(name) for name in dirnames}
    for name, records in loaded.items():
        if not records:
            raise SystemExit(f"{name}/ 가 비어 있다")
    common = sorted(set.intersection(*(set(r) for r in loaded.values())))
    print(f"공통 출원 {len(common)}건 (조건: {' vs '.join(dirnames)})\n")

    width = max(len(name) for name in dirnames)
    header = "출원번호        라벨  " + "  ".join(
        f"{name:>{max(width, 14)}}" for name in dirnames
    )
    print(header + "   (recall 적중/전체 · 최고강도)")
    aggregate = {name: [0, 0] for name in dirnames}
    for number in common:
        cells = []
        label = loaded[dirnames[0]][number]["label"]
        for name in dirnames:
            record = loaded[name][number]
            hits = len(record["recall_hits"])
            total = hits + len(record["recall_misses"])
            aggregate[name][0] += hits
            aggregate[name][1] += total
            cells.append(
                f"{hits}/{total} · {_top_strength(record):.2f}".rjust(max(width, 14))
            )
        print(f"{number}  {label}    " + "  ".join(cells))

    print("\nrecall 합계 (공통 표본만):")
    for name in dirnames:
        hits, total = aggregate[name]
        share = f" ({hits / total:.0%})" if total else ""
        print(f"  {name:24s} {hits}/{total}{share}")

    print("\n건별 최고 강도 평균 (공통 표본만):")
    for name in dirnames:
        tops = [_top_strength(loaded[name][number]) for number in common]
        print(f"  {name:24s} {sum(tops) / len(tops):.3f}")


if __name__ == "__main__":
    main()
