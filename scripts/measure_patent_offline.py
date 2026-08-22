"""KIPRIS 호출 없이 특허 등급 분포를 잰다.

무료 등급의 호출 한도는 월 1,000 회이고 분석 한 건이 11 회쯤 쓴다. 개발 중에
분포를 반복해서 보려면 검색·상세조회를 고정 코퍼스로 대신해야 한다.
대조는 실제 모델을 그대로 쓴다 — 등급을 만드는 것이 그쪽이기 때문이다.

    GEMINI_MODEL_ID=... GCP_PROJECT_ID=... python scripts/measure_patent_offline.py

특허 본문은 합성이다 (`tests/fixtures/kipris/README.md`). 파이프라인이 무엇을
내놓는지 보는 용도이고, 여기서 나온 근거로 실제 IP 판단을 하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope

from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.offline_corpus import (
    load_corpus,
    offline_kipris_client,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "kipris" / "corpus.json"


def _artifact(path: Path) -> AnalysisArtifact:
    body = path.read_text(encoding="utf-8")
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id=f"offline:{path.stem}",
        risk_workspace_id="offline-vws",
        mount_id="offline-mount",
        artifact_id=f"offline-artifact:{path.stem}",
        logical_path=f"/offline/{path.name}",
        revision="rev-1",
        artifact_kind=ArtifactKind.DOCUMENT_TEXT,
        mime_type="text/markdown",
        requested_analyzers=[AnalysisType.PATENT],
        content_scope=ContentScope.FULL_TEXT,
        text_segments=split_document(body),
        security_context=AnalysisSecurityContext(
            approved=True,
            policy_version="offline",
            redaction_count=0,
            original_checksum="sha256:offline",
            analysis_input_checksum="sha256:offline",
        ),
        created_at=datetime.now(timezone.utc),
    )


async def run(documents: list[Path]) -> int:
    # 합성 코퍼스는 의도를 명시해야 열린다. 이 스크립트가 그 의도다.
    corpus = load_corpus(CORPUS, acknowledge_synthetic=True)
    client = offline_kipris_client(corpus, acknowledge_synthetic=True)
    model = GoogleGenAIClient(
        os.environ["GEMINI_MODEL_ID"],
        vertex_config={
            "vertexai": True,
            "project": os.environ["GCP_PROJECT_ID"],
            "location": os.environ.get("VERTEX_LOCATION", "global"),
        },
    )
    analyzer = PatentAnalyzer(client, model, candidate_cap=6)

    grades: Counter[str] = Counter()
    matches: Counter[int] = Counter()
    truncated = Counter()
    caveats: Counter[int] = Counter()

    for path in documents:
        artifact = _artifact(path)
        result = await analyzer.analyze(artifact)
        print(
            f"--- {path.name}: segments={len(artifact.text_segments)} "
            f"status={result.status.value} coverage={result.coverage.value} "
            f"candidates={len(result.candidates)}"
        )
        for failure in result.provider_failures:
            print(f"      FAILURE {failure.provider}/{failure.category}: {failure.safe_message}")
        for candidate in result.candidates:
            meta = candidate.provider_metadata_safe
            grades[candidate.suggested_review_priority.value] += 1
            matches[len(candidate.matched_elements)] += 1
            truncated[bool(meta.get("evidence_truncated"))] += 1
            caveats[len(meta.get("review_caveats") or [])] += 1
            print(
                f"      {candidate.suggested_review_priority.value:<6} "
                f"matched={len(candidate.matched_elements)} "
                f"claim={meta.get('has_claim_evidence')} "
                f"truncated={meta.get('evidence_truncated')} "
                f"strength={meta.get('evidence_strength')} "
                f"quotes={len(meta.get('quote_spans') or {})} "
                f"{candidate.normalized_application_number}"
            )

    await client.aclose()
    print()
    print(f"등급        : {dict(grades)}")
    print(f"겹침 개수    : {dict(sorted(matches.items()))}")
    print(f"근거 잘림    : {dict(truncated)}")
    print(f"참고사항 개수: {dict(sorted(caveats.items()))}")
    print(f"KIPRIS 실호출: 0 (고정 코퍼스 {len(client.offline_calls)} 회 대체)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--documents",
        default=str(ROOT / "samples" / "patent"),
        help="분석할 문서 디렉터리 또는 파일",
    )
    args = parser.parse_args()
    target = Path(args.documents)
    documents = sorted(target.glob("*.md")) if target.is_dir() else [target]
    if not documents:
        print("no documents", file=sys.stderr)
        return 2
    return asyncio.run(run(documents))


if __name__ == "__main__":
    raise SystemExit(main())
