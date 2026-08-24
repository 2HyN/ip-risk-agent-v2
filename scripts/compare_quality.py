"""모델 티어링 품질 비교 — ``compare-results.jsonl`` 을 문서·특허별로 나란히 세운다.

토큰 수는 비용을 말하지만 품질은 말하지 않는다. 이 스크립트는 같은
(문서, 출원번호) 조합에 대해 모델마다 무엇을 근거로 들었는지를 사람이 눈으로
비교할 수 있게 늘어놓기만 한다 — 판정은 사람이 한다.

    python scripts/compare_quality.py compare-results.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("log", help="cost_measure.py --compare-out 로 만든 JSONL")
    args = parser.parse_args()

    path = Path(args.log)
    if not path.is_file():
        print(f"{path} 없음 — cost_measure.py 를 먼저 실행하세요.")
        return 1

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        print("비교할 대조 결과가 없습니다.")
        return 1

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        groups[(r["doc"], r["application_number"])].append(r)

    for (doc, app_no), rows in sorted(groups.items()):
        print(f"\n{'=' * 70}")
        print(f"문서: {doc}  ·  출원번호: {app_no}")
        print("=" * 70)
        for row in sorted(rows, key=lambda r: r["model"]):
            print(f"\n  [{row['model']}]")
            print(f"    matched={len(row['matched_elements'])}"
                  f" distinct={len(row['distinct_elements'])}"
                  f" caveats={len(row['review_caveats'])}")
            for m in row["matched_elements"]:
                print(f"    - {m['explanation']}")
            if row["review_caveats"]:
                print(f"    caveats: {'; '.join(row['review_caveats'])}")

    print(f"\n\n총 {len(groups)}개 (문서, 특허) 조합, {len(records)}개 레코드.")
    print("같은 조합에서 모델별 matched 개수·설명 내용이 크게 다르면 그 모델은")
    print("품질 저하 후보다 — 여기서부터 사람이 직접 읽고 판단한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
