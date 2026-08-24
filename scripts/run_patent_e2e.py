"""특허 분석 고도화 흐름의 E2E 러너.

특정 후보 문서 파일 하나에 대해 제안된 전체 흐름(추출 v3 → 확장 검색 → RRF →
청구항 청킹 → ephemeral 인덱스 → 요소 색인 대조 → 검증 → 판정)을 온전히
수행한다 (`docs/PATENT_RAG_ENHANCEMENT_PLAN.md` §7 E1 게이트).

    # 합성 코퍼스(KIPRIS 0회) + 실제 Gemini
    GEMINI_MODEL_ID=... GEMINI_API_KEY=... python scripts/run_patent_e2e.py \
        --doc samples/patent/voice-phishing-detection-design.md \
        --search-strategy expanded_v1 --compare-strategy rag

    # 실제 KIPRIS (유료 등급, 초당 제한만 주의 — KIPRIS_MAX_RPS 로 조절)
    KIPRIS_ACCESS_KEY=... python scripts/run_patent_e2e.py --kipris live ...

    # 베이스라인과 나란히 비교
    python scripts/run_patent_e2e.py --search-strategy baseline --compare-strategy baseline

Gemini 는 항상 실제 호출이다 — 등급을 만드는 대조가 그쪽이기 때문이다
(`measure_patent_offline.py` 와 같은 원칙). Vertex 를 쓰려면 GCP_PROJECT_ID 를,
AI Studio 를 쓰려면 GEMINI_API_KEY 를 준다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope

from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.kipris import KiprisClient
from ip_risk_agent.intelligence.patent.offline_corpus import (
    load_corpus,
    offline_kipris_client,
)
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket
from ip_risk_agent.intelligence.patent.search_strategy import (
    plan_for,
    require_compare_strategy,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "kipris" / "corpus.json"
DEFAULT_DOC = ROOT / "samples" / "patent" / "voice-phishing-detection-design.md"


def _artifact(path: Path) -> AnalysisArtifact:
    body = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id=f"e2e:{path.stem}",
        risk_workspace_id="e2e-vws",
        mount_id="e2e-mount",
        artifact_id=f"e2e-artifact:{path.stem}",
        logical_path=f"/e2e/{path.name}",
        revision="rev-1",
        artifact_kind=ArtifactKind.DOCUMENT_TEXT,
        mime_type="text/markdown",
        requested_analyzers=[AnalysisType.PATENT],
        content_scope=ContentScope.FULL_TEXT,
        text_segments=split_document(body),
        security_context=AnalysisSecurityContext(
            approved=True,
            policy_version="e2e",
            redaction_count=0,
            original_checksum=f"sha256:{checksum}",
            analysis_input_checksum=f"sha256:{checksum}",
        ),
        created_at=datetime.now(timezone.utc),
    )


def _model_client() -> GoogleGenAIClient:
    model_id = os.environ.get("GEMINI_MODEL_ID")
    if not model_id:
        raise SystemExit("GEMINI_MODEL_ID is required")
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return GoogleGenAIClient(model_id, api_key=api_key)
    project = os.environ.get("GCP_PROJECT_ID")
    if not project:
        raise SystemExit("either GEMINI_API_KEY or GCP_PROJECT_ID is required")
    return GoogleGenAIClient(
        model_id,
        vertex_config={
            "vertexai": True,
            "project": project,
            "location": os.environ.get("VERTEX_LOCATION", "global"),
        },
    )


def _search_provider(kind: str):
    if kind == "corpus":
        corpus = load_corpus(CORPUS, acknowledge_synthetic=True)
        return offline_kipris_client(corpus, acknowledge_synthetic=True)
    access_key = os.environ.get("KIPRIS_ACCESS_KEY")
    if not access_key:
        raise SystemExit("KIPRIS_ACCESS_KEY is required for --kipris live")
    max_rps = os.environ.get("KIPRIS_MAX_RPS")
    return KiprisClient(
        access_key,
        rate_limiter=TokenBucket(float(max_rps)) if max_rps else None,
    )


def _candidate_row(candidate) -> dict:
    metadata = dict(candidate.provider_metadata_safe)
    return {
        "application_number": candidate.normalized_application_number,
        "title": candidate.title,
        "priority": candidate.suggested_review_priority.value,
        "matched_elements": candidate.matched_elements,
        "evidence_ids": candidate.evidence_ids,
        "evidence_strength": metadata.get("evidence_strength"),
        "distinct_match_count": metadata.get("distinct_match_count"),
        "compare_strategy": metadata.get("compare_strategy", "baseline"),
        "rank_version": metadata.get("rank_version"),
        "context_chunks": metadata.get("context_chunks"),
        "retrieved_chunks": metadata.get("retrieved_chunks"),
        "context_incomplete": metadata.get("context_incomplete"),
    }


async def run(args: argparse.Namespace) -> int:
    document = Path(args.doc)
    if not document.is_file():
        raise SystemExit(f"document not found: {document}")

    provider = _search_provider(args.kipris)
    analyzer = PatentAnalyzer(
        provider,
        _model_client(),
        search_plan=plan_for(args.search_strategy),
        compare_strategy=require_compare_strategy(args.compare_strategy),
    )

    started = datetime.now(timezone.utc)
    result = await analyzer.analyze(_artifact(document))
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    summary = {
        "document": document.name,
        "kipris": args.kipris,
        "search_strategy": args.search_strategy,
        "compare_strategy": args.compare_strategy,
        "status": result.status.value,
        "coverage": result.coverage.value,
        "elapsed_seconds": round(elapsed, 1),
        "versions": {
            "analyzer": result.versions.analyzer_version,
            "model": result.versions.model_id,
            "prompt": result.versions.prompt_version,
        },
        "provider_failures": [
            {"provider": failure.provider, "category": failure.category}
            for failure in result.provider_failures
        ],
        "candidates": [_candidate_row(candidate) for candidate in result.candidates],
        "evidence_count": len(result.evidence),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    close = getattr(provider, "aclose", None)
    if close is not None:
        await close()
    return 0


def main() -> int:
    # Windows 콘솔(cp949)에서 한국어 출력·도움말이 깨지지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", default=str(DEFAULT_DOC), help="분석할 문서 파일")
    parser.add_argument(
        "--kipris",
        choices=("corpus", "live"),
        default="corpus",
        help="corpus=합성 코퍼스(호출 0회, 기본) / live=실제 KIPRIS",
    )
    parser.add_argument(
        "--search-strategy",
        choices=("baseline", "expanded_v1"),
        default="expanded_v1",
    )
    parser.add_argument(
        "--compare-strategy", choices=("baseline", "rag"), default="rag"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="단계별 진단 이벤트(patent_search_diagnostic 등)를 stderr 로 보여 준다",
    )
    args = parser.parse_args()
    if args.verbose:
        import logging

        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
