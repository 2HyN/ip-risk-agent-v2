"""v4 측정용 질의 추출 + 풀 수집 — 클라이언트 수정과 프롬프트 효과를 분리한다.

수집 축 두 개 (`--pass61` / `--pass62`):

  61  v3 질의(labels/diagnosis/queries-*.json 그대로) × **수정된 클라이언트**
      (`*` AND + 필드별 무절단) → poolv2-<출원>-r61.json
  62  v4 질의(patent_extract_v4 신규 추출 + 확장 cap24, queriesv4-*.json 캐시)
      × 수정된 클라이언트 → poolv2-<출원>-r62.json

61 과 기존 r60(깨진 클라이언트)의 차이 = 클라이언트 수정 효과,
62 와 61 의 차이 = 질의 생성 v4 효과. 접미사를 정수로 둔 것은 기존 측정
하네스(load_cases(rows=…))가 그대로 읽게 하기 위해서다.

공용 키 규칙: 호출 간격 0.7초 이상 (검색 1회 = 필드 2회 호출이므로 검색당
1.5초 대기).

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GCP_PROJECT_ID=... GOLDEN_DIR=... \
      .venv/Scripts/python scripts/collect_pools_v4.py --extract   # v4 질의 추출
    ... --pass61
    ... --pass62
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import _repo_path  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
DIAG = ROOT / "labels" / "diagnosis"
POOL = ROOT / "labels" / "rank-ablation"
SEARCH_SLEEP = 1.5  # 검색 1회 = 필드 2회 호출 — 공용 키 0.7초/호출 규칙


def _cited_apps() -> list[str]:
    rows = [
        json.loads(line)
        for line in (GOLDEN / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted(
        r["application_number"] for r in rows if r.get("examiner_cited")
    )


def _abstract(number: str) -> str:
    from defusedxml.ElementTree import fromstring

    path = GOLDEN / "raw" / f"biblio-{number}.xml"
    root = fromstring(path.read_text(encoding="utf-8"))
    return next((n.text for n in root.iter("astrtCont") if n.text), "") or ""


async def extract() -> int:
    from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
    from ip_risk_agent.intelligence.patent.extraction import (
        TechnicalExtractor,
        expand_queries,
    )
    from ip_risk_agent.intelligence.patent.search_strategy import FIELDED_V4_PLAN
    from iprisk_contracts import AnalysisArtifact
    from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
    from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope
    from ip_risk_agent.connectors.common.segmentation import split_document

    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project:
        raise SystemExit("GCP_PROJECT_ID 필요")
    model = GoogleGenAIClient(
        os.environ.get("GEMINI_MODEL_ID") or os.environ.get(
            "GEMINI_MODEL", "gemini-3.6-flash"
        ),
        vertex_config={"vertexai": True, "project": project, "location": "global"},
    )
    extractor = TechnicalExtractor(
        model,
        prompt_name=FIELDED_V4_PLAN.extract_prompt,
        max_queries=FIELDED_V4_PLAN.max_queries,
    )
    done = 0
    for number in _cited_apps():
        out = DIAG / f"queriesv4-{number}.json"
        if out.exists():
            continue
        abstract = _abstract(number)
        if not abstract:
            continue
        artifact = AnalysisArtifact(
            contract_version="1",
            analysis_job_id=f"v4:{number}",
            risk_workspace_id="golden-vws",
            mount_id="golden-mount",
            artifact_id=f"v4:{number}",
            logical_path=f"/golden/{number}.txt",
            revision="rev-1",
            artifact_kind=ArtifactKind.DOCUMENT_TEXT,
            mime_type="text/plain",
            requested_analyzers=[AnalysisType.PATENT],
            content_scope=ContentScope.FULL_TEXT,
            text_segments=split_document(abstract),
            security_context=AnalysisSecurityContext(
                approved=True,
                policy_version="golden-eval",
                redaction_count=0,
                original_checksum=f"sha256:v4-{number}",
                analysis_input_checksum=f"sha256:v4-{number}",
            ),
            created_at=datetime.now(timezone.utc),
        )
        extraction = await extractor.extract(artifact)
        queries = expand_queries(
            extraction.search_queries, cap=FIELDED_V4_PLAN.expansion_cap
        )
        out.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
        done += 1
        print(f"  {number}: 질의 {len(queries)}개")
    print(f"추출 {done}건 (캐시 재사용 {len(_cited_apps()) - done}건)")
    return 0


async def collect(prefix: str, tag: int) -> int:
    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요")
    client = KiprisClient(key, search_fields=("inventionTitle", "astrtCont"))
    searches = 0
    try:
        for number in _cited_apps():
            out = POOL / f"poolv2-{number}-r{tag}.json"
            if out.exists():
                continue
            qpath = DIAG / f"{prefix}-{number}.json"
            if not qpath.exists():
                print(f"  {number}: 질의 캐시 없음 — 건너뜀")
                continue
            queries = json.loads(qpath.read_text(encoding="utf-8"))
            pool = {}
            for query in queries:
                for attempt in range(3):
                    try:
                        hits = await client.search(query, rows=60)
                        break
                    except Exception as exc:  # noqa: BLE001 — 일시 오류 재시도
                        if attempt == 2:
                            raise
                        print(f"    재시도({exc.__class__.__name__}): {query}")
                        await asyncio.sleep(5 * (attempt + 1))
                searches += 1
                if hits:
                    pool[query] = [
                        {
                            "application_number": h.application_number,
                            "title": h.title,
                            "metadata": h.metadata,
                            "abstract": h.abstract,
                        }
                        for h in hits
                    ]
                await asyncio.sleep(SEARCH_SLEEP)
            out.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
            print(f"  {number}: 질의 {len(queries)}개 수집")
    finally:
        await client.aclose()
    print(f"수집 완료 — 검색 {searches}회")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--pass61", action="store_true")
    parser.add_argument("--pass62", action="store_true")
    args = parser.parse_args()
    if args.extract:
        sys.exit(asyncio.run(extract()))
    if args.pass61:
        sys.exit(asyncio.run(collect("queries", 61)))
    if args.pass62:
        sys.exit(asyncio.run(collect("queriesv4", 62)))
    parser.error("--extract / --pass61 / --pass62")


if __name__ == "__main__":
    main()
