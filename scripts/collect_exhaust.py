"""P1a 적응적 소진 탐색 — 작은 결과집합 질의는 끝까지 판다.

도달성 분류의 발견: 현행 질의가 인용에 매치하는데(A1) 결과집합에 묻혀 풀에
못 든 30건 중 7건은 결과집합이 300건 이하다. AND 질의의 결과집합이 작다는
것은 그 질의가 정밀하다는 뜻이고, 그 안에 인용이 확실히 있으므로(A1 정의)
**전 페이지를 받아 오면 회수는 재순위(BM25+정밀꼬리)가 맡는다**.

r60 풀 캐시를 기반으로, 질의×필드의 totalCount 가 60 초과 300 이하인 것만
pageNo 2.. 를 추가로 받아 확장 풀을 ``poolv2-<출원>-r600.json`` (600 은
"소진" 표기)로 저장한다 — 기존 스위프·측정 하네스가 ``--rows 600`` 으로
그대로 읽는다.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GOLDEN_DIR=... \
      .venv/Scripts/python scripts/collect_exhaust.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import _repo_path  # noqa: F401

import httpx
from defusedxml.ElementTree import fromstring

from ip_risk_agent.intelligence.patent.kipris import (
    ADVANCED_SEARCH_PATH,
    BASE_URL,
    normalize_application_number,
)

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "labels" / "rank-ablation"
PAGE = 60
TOTAL_CAP = 300  # 이 이하의 결과집합만 소진한다 — 정밀 질의의 정의


def _page(key: str, field: str, query: str, page_no: int) -> tuple[str, list[dict]]:
    response = httpx.get(
        f"{BASE_URL}/{ADVANCED_SEARCH_PATH}",
        params={
            field: query,
            "patent": "true",
            "utility": "true",
            "pageNo": str(page_no),
            "numOfRows": str(PAGE),
            "ServiceKey": key,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    root = fromstring(response.text)
    total = (root.findtext(".//totalCount") or "").strip()
    hits = []
    for element in root.iter("item"):
        number = normalize_application_number(
            element.findtext("applicationNumber") or ""
        )
        if not number:
            continue
        metadata = {
            "applicationDate": (element.findtext("applicationDate") or "").strip(),
            "openDate": (element.findtext("openDate") or "").strip(),
            "ipc": (element.findtext("ipcNumber") or "").strip(),
            "search_field": field,
        }
        if total.isdigit():
            metadata["search_total"] = total
        hits.append(
            {
                "application_number": number,
                "title": (element.findtext("inventionTitle") or "").strip(),
                "metadata": metadata,
                "abstract": (element.findtext("astrtCont") or "").strip(),
            }
        )
    return total, hits


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key and not args.dry_run:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요")

    planned_pages = 0
    fetched_pages = 0
    for path in sorted(POOL.glob("poolv2-*-r60.json")):
        number = path.stem.replace("poolv2-", "").replace("-r60", "")
        out = POOL / f"poolv2-{number}-r600.json"
        if out.exists():
            continue
        pool = json.loads(path.read_text(encoding="utf-8"))
        # 질의×필드별 total 과 이미 가진 건수
        targets = []  # (query, field, total, have)
        for query, hits in pool.items():
            per_field: dict[str, list[dict]] = {}
            for hit in hits:
                per_field.setdefault(
                    hit["metadata"].get("search_field", ""), []
                ).append(hit)
            for field, field_hits in per_field.items():
                total = field_hits[0]["metadata"].get("search_total", "")
                if not str(total).isdigit():
                    continue
                total = int(total)
                if PAGE < total <= TOTAL_CAP:
                    targets.append((query, field, total, len(field_hits)))
        pages = sum(math.ceil(t / PAGE) - 1 for _, _, t, _ in targets)
        planned_pages += pages
        if args.dry_run:
            continue
        for query, field, total, _ in targets:
            seen = {h["application_number"] for h in pool[query]}
            for page_no in range(2, math.ceil(total / PAGE) + 1):
                _, hits = _page(key, field, query, page_no)
                fetched_pages += 1
                for hit in hits:
                    if hit["application_number"] not in seen:
                        seen.add(hit["application_number"])
                        pool[query].append(hit)
                time.sleep(0.25)
        out.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
        print(f"  {number}: 소진 대상 {len(targets)}개 질의×필드, +{pages}페이지")
    if args.dry_run:
        print(f"계획: 추가 페이지 {planned_pages}건 (호출 수와 동일)")
    else:
        print(f"완료: 추가 페이지 {fetched_pages}건")


if __name__ == "__main__":
    main()
