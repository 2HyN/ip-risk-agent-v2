"""recall 재채점 — 번호 체계 버그를 바로잡는다.

## 무엇이 틀렸었나

심사관 인용의 "공개특허공보 제10-2012-0106424호" 는 **공개번호**다. 출원번호와
형식(10-YYYY-NNNNNNN)이 같아서 처음 채점은 이것을 출원번호로 취급해 후보의
출원번호와 직접 비교했다 — 절대 맞을 수 없는 대조였다. 역방향 테스트로
확인했다: 그 번호를 출원번호로 조회하면 전혀 다른 분야의 특허가 나온다.

## 올바른 대조

후보 출원마다 공보 상세에서 세 번호를 모두 수집해 인용 번호를 셋 다에 대조한다.

* applicationNumber — 출원번호 (13자리)
* openNumber       — 공개번호 (13자리, 출원번호와 다른 값)
* registerNumber   — 등록번호 (10자리)

파이프라인 재실행은 필요 없다 — eval 기록의 후보 목록은 그대로이고 채점만
다시 한다. 후보의 공보가 캐시에 없으면 1회 조회 후 캐시한다.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... \
      .venv/Scripts/python scripts/rescore_golden.py eval eval-improved eval-improved-expand
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from defusedxml.ElementTree import fromstring

from ip_risk_agent.intelligence.patent.kipris import (
    BASE_URL,
    DETAIL_PATH,
    normalize_application_number,
)

ROOT = Path(__file__).resolve().parents[1]
# 골든셋이 저장소 밖(팀 공유 폴더)에 있으면 GOLDEN_DIR 로 가리킨다.
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
RAW_DIR = GOLDEN / "raw"


def _candidate_numbers(number: str, key: str) -> set[str]:
    """후보 출원의 출원·공개·등록 번호 전부 (숫자만). 캐시 우선."""
    path = RAW_DIR / f"biblio-{number}.xml"
    if not path.exists():
        # 공용 키 수칙: 호출 간격 1인당 최소 0.7초. 간격 없이 연사하면 서버가
        # 연결을 끊는다 (WinError 10054 실측). 일시 오류는 1회 재시도.
        import time

        for attempt in (1, 2):
            try:
                response = httpx.get(
                    f"{BASE_URL}/{DETAIL_PATH}",
                    params={"applicationNumber": number, "ServiceKey": key},
                    timeout=20.0,
                )
                response.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 2:
                    raise
                time.sleep(5.0)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
        time.sleep(0.85)
    root = fromstring(path.read_text(encoding="utf-8"))
    numbers = set()
    for tag in ("applicationNumber", "openNumber", "registerNumber", "publicationNumber"):
        for node in root.iter(tag):
            digits = normalize_application_number(node.text or "")
            if digits:
                numbers.add(digits)
    return numbers


def main() -> None:
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요 (미캐시 후보의 공보 조회용)")
    dirnames = sys.argv[1:] or ["eval"]
    lookups = 0
    known: dict[str, set[str]] = {}
    for dirname in dirnames:
        rescored_hits = 0
        rescored_total = 0
        changed = 0
        for path in sorted((GOLDEN / dirname).glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            cited = record.get("examiner_cited") or []
            if not cited:
                continue
            pool: set[str] = set()
            for candidate in record["candidates"]:
                number = candidate["application_number"]
                if number not in known:
                    cached = (RAW_DIR / f"biblio-{number}.xml").exists()
                    known[number] = _candidate_numbers(number, key)
                    if not cached:
                        lookups += 1
                pool |= known[number]
            hits, misses = [], []
            for citation in cited:
                digits = normalize_application_number(citation)
                (hits if digits in pool else misses).append(digits)
            before = len(record.get("recall_hits") or [])
            if len(hits) != before:
                changed += 1
            record["recall_hits"] = hits
            record["recall_misses"] = misses
            record["rescored"] = "open+register+application numbers"
            path.write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            rescored_hits += len(hits)
            rescored_total += len(cited)
        share = f" ({rescored_hits / rescored_total:.0%})" if rescored_total else ""
        print(
            f"{dirname:24s} recall {rescored_hits}/{rescored_total}{share}"
            f" · 적중 수 바뀐 건 {changed}건"
        )
    print(f"공보 신규 조회 {lookups}회")


if __name__ == "__main__":
    main()
