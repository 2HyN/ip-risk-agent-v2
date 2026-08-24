"""골든셋 평가 집계 — eval/ 의 건별 기록을 지표로 만든다.

계산하는 것:

* **recall** — 심사관 인용 문헌 중 후보 6개에 든 비율 (문헌 단위 / 건 단위)
* **강도 × 라벨** — 건별 최고 evidence_strength 의 라벨별 분포와
  순서 상관(Spearman 부호만 — 표본이 작아 계수 자체보다 방향이 중요하다)
* **등급 × 라벨** — suggested_review_priority 가 라벨과 같이 움직이는가

읽는 법에 대한 주의 (평가 설계의 한계 — 숫자에 별표를 붙일 이유들):

* 입력이 특허 초록이라 실사용 입력(기획서)보다 쉽다 — 수치는 **상한**이다
* 라벨 0 은 4건뿐이라 음성 쪽 통계는 방향만 봐라
* 심사관은 명세서 전문을, 우리는 초록만 대조했다 — recall 미스가 곧
  "우리가 틀렸다" 는 아니다. 다만 개선 지점의 목록으로는 정확하다
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "labels" / "golden" / "eval"


def main() -> None:
    global EVAL_DIR
    if len(sys.argv) > 1:
        EVAL_DIR = ROOT / "labels" / "golden" / sys.argv[1]
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(EVAL_DIR.glob("*.json"))
    ]
    if not records:
        raise SystemExit("eval/ 에 결과가 없다 — evaluate_golden.py 를 먼저 돌려라")

    by_label: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        by_label[record["label"]].append(record)

    print(f"평가 {len(records)}건: " + " · ".join(
        f"라벨{label} {len(rows)}건" for label, rows in sorted(by_label.items())
    ))

    # ── recall (라벨 1·2 중 인용이 있는 건만 — 인용 없는 건은 정답이 없다)
    cited_rows = [r for r in records if r["examiner_cited"]]
    doc_hits = sum(len(r["recall_hits"]) for r in cited_rows)
    doc_total = sum(
        len(r["recall_hits"]) + len(r["recall_misses"]) for r in cited_rows
    )
    any_hit = sum(1 for r in cited_rows if r["recall_hits"])
    print(
        f"\nrecall  문헌 단위 {doc_hits}/{doc_total}"
        f" ({doc_hits / doc_total:.0%})" if doc_total else "\nrecall  대조할 인용 없음",
    )
    if cited_rows:
        print(
            f"        건 단위(하나라도 적중) {any_hit}/{len(cited_rows)}"
            f" ({any_hit / len(cited_rows):.0%})"
        )

    # ── 강도 × 라벨
    print("\n건별 최고 evidence_strength:")
    label_means: list[tuple[int, float]] = []
    for label, rows in sorted(by_label.items()):
        tops = []
        for r in rows:
            strengths = [
                float(c["strength"]) for c in r["candidates"] if c["strength"]
            ]
            tops.append(max(strengths) if strengths else 0.0)
        mean = sum(tops) / len(tops) if tops else 0.0
        label_means.append((label, mean))
        shown = " ".join(f"{t:.2f}" for t in sorted(tops, reverse=True))
        print(f"  라벨{label}: 평균 {mean:.3f}  [{shown}]")
    direction = all(
        earlier[1] <= later[1]
        for earlier, later in zip(label_means, label_means[1:])
    )
    print(f"  단조 증가(라벨↑ ⇒ 강도↑)? {'예' if direction else '아니오'}")

    # ── 등급 × 라벨
    print("\n건별 최고 등급 분포:")
    order = {"LOW": 0, "MEDIUM": 1, "INDETERMINATE": 1, "HIGH": 2}
    for label, rows in sorted(by_label.items()):
        grades = Counter()
        for r in rows:
            best = max(
                (c["priority"] for c in r["candidates"]),
                key=lambda g: order.get(g, -1),
                default="(후보없음)",
            )
            grades[best] += 1
        print(f"  라벨{label}: {dict(grades)}")

    # ── 실패·이상 신호
    failures = Counter()
    for r in records:
        for f in r["failures"]:
            failures[f] += 1
    if failures:
        print(f"\nprovider 실패: {dict(failures)}")

    # ── 다음에 볼 것: 놓친 인용 목록 (개선 지점)
    print("\n놓친 인용 (파이프라인이 못 데려온 심사관 문헌):")
    for r in records:
        if r["recall_misses"]:
            print(f"  {r['application_number']} (label={r['label']}): {r['recall_misses']}")


if __name__ == "__main__":
    main()
