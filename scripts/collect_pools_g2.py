"""goldset2 (206출원) 의 검색 평가 확장 — v4 질의 추출 + 풀 수집.

기존 37출원 하네스(collect_pools_v4)와 같은 원리, 입력만 goldset2 파생물
(labels/goldset2/pairs2.jsonl · source_biblio.json). 산출:

  질의: labels/diagnosis/queriesg2-<출원>.json  (v4 프롬프트, 1회 추출 고정)
  풀:   labels/rank-ablation/poolg2-<출원>.json (rows 60, 필드 2, `*` AND)

공용 키 규칙: 검색 1회 = 필드 2회 호출 → 검색당 1.5초 대기.

    ... --extract   (Gemini, 출원당 1회)
    ... --collect   (KIPRIS)
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
G2 = ROOT / "labels" / "goldset2"
DIAG = ROOT / "labels" / "diagnosis"
POOL = ROOT / "labels" / "rank-ablation"
SEARCH_SLEEP = 1.5


def _apps() -> list[dict]:
    return [
        json.loads(line)
        for line in (G2 / "pairs2.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _abstracts() -> dict[str, str]:
    biblio = json.loads((G2 / "source_biblio.json").read_text(encoding="utf-8"))
    return {k: v.get("abstract", "") for k, v in biblio.items()}


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
    abstracts = _abstracts()
    done = skip = 0
    for row in _apps():
        number = row["application_number"]
        out = DIAG / f"queriesg2-{number}.json"
        if out.exists():
            continue
        abstract = abstracts.get(number, "")
        if not abstract:
            skip += 1
            continue
        artifact = AnalysisArtifact(
            contract_version="1",
            analysis_job_id=f"g2:{number}",
            risk_workspace_id="golden-vws",
            mount_id="golden-mount",
            artifact_id=f"g2:{number}",
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
                original_checksum=f"sha256:g2-{number}",
                analysis_input_checksum=f"sha256:g2-{number}",
            ),
            created_at=datetime.now(timezone.utc),
        )
        try:
            extraction = await extractor.extract(artifact)
        except Exception as exc:  # noqa: BLE001
            print(f"  {number}: 추출 실패 {type(exc).__name__}")
            continue
        queries = expand_queries(
            extraction.search_queries, cap=FIELDED_V4_PLAN.expansion_cap
        )
        out.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
        done += 1
        if done % 25 == 0:
            print(f"  질의 추출 {done}")
    print(f"추출 {done}건 · 초록 없음 {skip}건")
    return 0


async def collect() -> int:
    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요")
    client = KiprisClient(key, search_fields=("inventionTitle", "astrtCont"))
    searches = 0
    try:
        for row in _apps():
            number = row["application_number"]
            out = POOL / f"poolg2-{number}.json"
            if out.exists():
                continue
            qpath = DIAG / f"queriesg2-{number}.json"
            if not qpath.exists():
                continue
            queries = json.loads(qpath.read_text(encoding="utf-8"))
            pool = {}
            for query in queries:
                for attempt in range(3):
                    try:
                        hits = await client.search(query, rows=60)
                        break
                    except Exception as exc:  # noqa: BLE001
                        if attempt == 2:
                            raise
                        print(f"    재시도({type(exc).__name__}): {query}")
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
            POOL.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
            print(f"  {number}: 질의 {len(queries)}개 수집 (누적 검색 {searches})")
    finally:
        await client.aclose()
    print(f"수집 완료 — 검색 {searches}회")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    if args.extract:
        sys.exit(asyncio.run(extract()))
    if args.collect:
        sys.exit(asyncio.run(collect()))
    parser.error("--extract / --collect")


if __name__ == "__main__":
    main()
