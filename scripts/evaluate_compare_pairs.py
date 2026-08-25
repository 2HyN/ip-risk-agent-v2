"""대조 층(Layer C) 골든셋 평가 — 심사관 확정 쌍에서 대조 전략을 A/B 한다.

## 무엇을 재는가

``verification_pairs_157.csv`` 의 각 행은 심사관이 신규성(§29①) 거절에 쓴
**확정 쌍**이다: 출원인의 청구항(target_claims) ↔ 인용 공개공보. 즉 모든 행의
정답은 "매칭이 존재한다"이고, 질문은 **우리 대조가 그것을 찾아내는가**다.

검색 축은 상수로 고정한다 — 어떤 질의든 인용 특허 1건만 돌려주는 provider 를
쓰므로 검색 품질이 결과에 섞이지 않는다. 대조 전략(baseline v2 / rag v3)만
바꿔 같은 쌍을 두 번 돌리면 쌍대 비교가 된다.

## 인용 문헌의 청구항·초록

CSV 의 cited_fulltext 는 공보 전문 텍스트라 절 구조가 불안정하다(청구범위
마커가 50/157). 대신 전문의 "(21) 출원번호" 로 KIPRIS 상세를 1회 받아
운영과 같은 모양(제목·초록·청구항)을 쓴다. 응답은 JSON 으로 캐시되므로
재실행·전략 추가에 추가 호출이 없다 (고유 인용 특허 110건).

## 비용

쌍·전략당 Gemini 2회(추출 1 + 대조 1). KIPRIS 는 캐시 미스에만 상세 1회.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GCP_PROJECT_ID=... \
      .venv/Scripts/python scripts/evaluate_compare_pairs.py --limit 3

집계만 다시 보려면 ``--summarize`` (API 호출 없음).
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import csv
import json
import os
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다
from _gcloud_creds import maybe_inject

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope

from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.kipris import (
    KiprisClient,
    PatentDocument,
    PatentSearchHit,
)
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket
from ip_risk_agent.intelligence.patent.search_strategy import BASELINE_PLAN

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAIRS = (
    ROOT.parent / "patent_goldsets" / "PatentComparison" / "verification_pairs_157.csv"
)
OUT_ROOT = ROOT / "labels" / "compare-eval"  # labels/ 는 gitignore — 데이터 비공개

_APP_NO = re.compile(r"\(21\)\s*출\s*원\s*번\s*호\s*([0-9\-]+)")

STRATEGIES = ("baseline", "rag")

# goldset2 전문은 128KB 기본 한도를 넘는다.
csv.field_size_limit(10**8)


def _cited_application_number(fulltext: str) -> str | None:
    match = _APP_NO.search(fulltext)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return digits if len(digits) == 13 else None


def _artifact(number: str, claims_text: str) -> AnalysisArtifact:
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id=f"compare-golden:{number}",
        risk_workspace_id="golden-vws",
        mount_id="golden-mount",
        artifact_id=f"compare-golden:{number}",
        logical_path=f"/golden/{number}-claims.txt",
        revision="rev-1",
        artifact_kind=ArtifactKind.DOCUMENT_TEXT,
        mime_type="text/plain",
        requested_analyzers=[AnalysisType.PATENT],
        content_scope=ContentScope.FULL_TEXT,
        text_segments=split_document(claims_text),
        security_context=AnalysisSecurityContext(
            approved=True,
            policy_version="golden-eval",
            redaction_count=0,
            original_checksum=f"sha256:compare-golden-{number}",
            analysis_input_checksum=f"sha256:compare-golden-{number}",
        ),
        created_at=datetime.now(timezone.utc),
    )


class SingleCandidateProvider:
    """어떤 질의든 인용 특허 1건만 돌려준다 — 검색 축을 상수로 고정한다."""

    def __init__(self, hit: PatentSearchHit, document: PatentDocument) -> None:
        self._hit = hit
        self._document = document

    async def search(self, query: str, *, rows: int = 5):
        return [replace(self._hit, query=query)]

    async def fetch_detail(self, application_number: str) -> PatentDocument:
        return self._document


async def _cited_document(
    number: str, cache_dir: Path, kipris: KiprisClient | None
) -> PatentDocument | None:
    """인용 특허의 상세. 캐시 우선, 미스에만 라이브 1회."""
    cache = cache_dir / f"{number}.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return PatentDocument(
            application_number=data["application_number"],
            title=data["title"],
            abstract=data["abstract"],
            claims=data["claims"],
            metadata=data.get("metadata", {}),
        )
    if kipris is None:
        return None
    document = await kipris.fetch_detail(number)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(
        json.dumps(
            {
                "application_number": document.application_number,
                "title": document.title,
                "abstract": document.abstract,
                "claims": list(document.claims),
                "metadata": dict(document.metadata),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, cache)
    return document


def _load_pairs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _model_client() -> GoogleGenAIClient:
    model_id = os.environ.get("GEMINI_MODEL_ID") or os.environ.get(
        "GEMINI_MODEL", "gemini-3.6-flash"
    )
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        return GoogleGenAIClient(model_id, api_key=gemini_key)
    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project:
        raise SystemExit("GEMINI_API_KEY 또는 GCP_PROJECT_ID(Vertex ADC) 가 필요하다")
    return GoogleGenAIClient(
        model_id,
        vertex_config=maybe_inject({
            "vertexai": True,
            "project": project,
            "location": os.environ.get("VERTEX_LOCATION", "global"),
        }),
    )


async def run(
    pairs_csv: Path, limit: int, strategies: tuple[str, ...], offset: int = 0,
    tag: str = "",
) -> int:
    rows = _load_pairs(pairs_csv)[offset:]
    model = _model_client()

    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    max_rps = os.environ.get("KIPRIS_MAX_RPS", "").strip()
    kipris = (
        KiprisClient(
            access_key=key,
            rate_limiter=TokenBucket(float(max_rps)) if max_rps else None,
        )
        if key
        else None
    )
    cache_dir = OUT_ROOT / "raw"

    done = 0
    try:
        for row in rows:
            if done >= limit:
                break
            target = row["applicationNumber"].strip()
            # 선해석 열이 있으면 우선한다 (goldset2 파생 CSV) — 없으면 (21) 줄.
            cited = (row.get("citedApplicationNumber") or "").strip() or None
            if cited is not None and len(cited) != 13:
                cited = None
            if cited is None:
                cited = _cited_application_number(row["cited_fulltext"])
            if cited is None:
                print(f"  {target}: 인용 공보에서 출원번호 추출 실패 — 건너뜀")
                continue

            pending = [
                strategy
                for strategy in strategies
                if not (OUT_ROOT / f"eval-{strategy}{tag}" / f"{target}-{cited}.json").exists()
            ]
            if not pending:
                continue  # 이미 평가함 — 재실행은 남은 것만 돈다

            claims = ast.literal_eval(row["target_claims"])
            claims_text = "\n\n".join(claims)
            document = await _cited_document(cited, cache_dir, kipris)
            if document is None or not document.has_content:
                print(f"  {target}: 인용 특허 {cited} 상세 없음 — 건너뜀")
                continue
            hit = PatentSearchHit(
                application_number=cited, title=document.title, query=""
            )
            provider = SingleCandidateProvider(hit, document)

            for strategy in pending:
                analyzer = PatentAnalyzer(
                    provider,
                    model,
                    candidate_cap=6,
                    search_plan=BASELINE_PLAN,  # 검색 축 고정 — 대조만 잰다
                    compare_strategy=strategy,
                )
                result = await analyzer.analyze(_artifact(target, claims_text))
                candidate = next(iter(result.candidates), None)
                metadata = (
                    dict(candidate.provider_metadata_safe) if candidate else {}
                )
                record = {
                    "application_number": target,
                    "cited_application": cited,
                    "send_number": row.get("sendNumber", ""),
                    "strategy": strategy,
                    "status": result.status.value,
                    "coverage": result.coverage.value,
                    "matched": bool(candidate and candidate.matched_elements),
                    "matched_elements": (
                        list(candidate.matched_elements) if candidate else []
                    ),
                    "priority": (
                        candidate.suggested_review_priority.value
                        if candidate
                        else None
                    ),
                    "evidence_strength": metadata.get("evidence_strength"),
                    "distinct_match_count": metadata.get("distinct_match_count"),
                    "failures": [
                        f"{f.provider}/{f.category}"
                        for f in result.provider_failures
                    ],
                }
                out_dir = OUT_ROOT / f"eval-{strategy}{tag}"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{target}-{cited}.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                print(
                    f"  {target} vs {cited} [{strategy}]:"
                    f" status={record['status']} matched={record['matched']}"
                    f" 강도={record['evidence_strength']}"
                )
            done += 1
    finally:
        if kipris is not None:
            await kipris.aclose()
    print(f"\n평가 {done}쌍 → {OUT_ROOT}")
    return 0


def summarize() -> int:
    """전략별 매칭 재현율 + 쌍대 표. API 호출 없음."""
    tables: dict[str, dict[str, dict]] = {}
    for strategy in STRATEGIES:
        directory = OUT_ROOT / f"eval-{strategy}"
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            tables.setdefault(strategy, {})[path.stem] = record
    if not tables:
        print("집계할 평가 결과가 없다")
        return 1
    for strategy, records in tables.items():
        ok = [r for r in records.values() if r["status"] == "SUCCEEDED"]
        matched = [r for r in ok if r["matched"]]
        strengths = sorted(
            float(r["evidence_strength"])
            for r in matched
            if r.get("evidence_strength")
        )
        median = strengths[len(strengths) // 2] if strengths else None
        print(
            f"{strategy}: 평가 {len(records)}건 (성공 {len(ok)}) —"
            f" 매칭 재현 {len(matched)}/{len(ok)}"
            f" ({len(matched) / len(ok):.0%})" if ok else f"{strategy}: 성공 0",
        )
        if median is not None:
            print(f"  강도 중앙값 {median:.2f} (매칭 {len(strengths)}건)")
    both = set.intersection(
        *(set(records) for records in tables.values())
    ) if len(tables) > 1 else set()
    if both:
        flips = {
            key: tuple(tables[s][key]["matched"] for s in STRATEGIES)
            for key in sorted(both)
        }
        b_only = [k for k, (b, r) in flips.items() if b and not r]
        r_only = [k for k, (b, r) in flips.items() if r and not b]
        print(f"\n쌍대 {len(both)}건: baseline만 매칭 {len(b_only)} · rag만 매칭 {len(r_only)}")
        for key in b_only[:10]:
            print(f"  baseline만: {key}")
        for key in r_only[:10]:
            print(f"  rag만: {key}")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=str(DEFAULT_PAIRS))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0,
                        help="앞의 N행을 건너뛴다 — 병렬 분할용. "
                             "겹쳐도 건너뛰기(결과 파일 존재)로 안전하다")
    parser.add_argument(
        "--compare-strategy",
        choices=("baseline", "rag", "both"),
        default="both",
    )
    parser.add_argument("--tag", default="",
                        help="결과 폴더 접미사 — 음성 쌍 평가는 -neg 로 분리")
    parser.add_argument("--summarize", action="store_true",
                        help="집계만 출력 (API 호출 없음)")
    args = parser.parse_args()
    if args.summarize:
        sys.exit(summarize())
    strategies = (
        STRATEGIES if args.compare_strategy == "both" else (args.compare_strategy,)
    )
    sys.exit(asyncio.run(run(Path(args.pairs), args.limit, strategies, args.offset, args.tag)))


if __name__ == "__main__":
    main()
