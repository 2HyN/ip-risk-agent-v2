"""goldset2 인용 특허의 상세(제목·초록·청구항)를 대조 캐시에 선적재한다.

병렬 평가 프로세스들이 각자 KIPRIS 를 부르면 공용 키 규칙이 깨진다 —
순차 1회(0.75초/호출)로 labels/compare-eval/raw/<출원>.json 을 채워 두면
평가는 키 없이(Gemini 만) 돈다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path

import _repo_path  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "labels" / "compare-eval" / "raw"
csv.field_size_limit(10**8)


async def main_async() -> int:
    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요")
    numbers: set[str] = set()
    for name in ("safe_negative_pairs.csv", "positive_pairs.csv"):
        path = ROOT / "labels" / "goldset2" / name
        for row in csv.DictReader(path.open(encoding="utf-8-sig", newline="")):
            appno = (row.get("citedApplicationNumber") or "").strip()
            if len(appno) == 13:
                numbers.add(appno)
    todo = sorted(n for n in numbers if not (CACHE / f"{n}.json").exists())
    print(f"인용 상세 선적재: 대상 {len(numbers)} · 미캐시 {len(todo)}")
    client = KiprisClient(key)
    CACHE.mkdir(parents=True, exist_ok=True)
    done = 0
    try:
        for number in todo:
            try:
                document = await client.fetch_detail(number)
            except Exception as exc:  # noqa: BLE001
                print(f"  {number}: 실패 {type(exc).__name__}")
                await asyncio.sleep(2.0)
                continue
            (CACHE / f"{number}.json").write_text(
                json.dumps(
                    {
                        "application_number": document.application_number,
                        "title": document.title,
                        "abstract": document.abstract,
                        "claims": list(document.claims),
                        "metadata": dict(document.metadata),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}")
            await asyncio.sleep(0.75)
    finally:
        await client.aclose()
    print(f"선적재 완료 {done}건")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
