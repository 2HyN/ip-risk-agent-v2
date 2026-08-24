"""검색 miss 원인 분해 — 놓친 심사관 인용을 도달 가능성으로 분류한다.

## 질문

recall 측정에서 어떤 검색 조건도 인용 문헌을 못 데려왔다. 왜인가?

1. **RANKED_OUT** — 지금 질의가 인용 문헌의 제목/초록에 AND-매치한다.
   검색은 반환했어야 하고, 순위·rows 상한에서 밀렸거나 색인 차이다.
2. **QUERY_GAP** — 지금 질의는 매치하지 않지만, 출원 초록의 어휘 중 2개
   이상이 인용 문헌 텍스트에 있다. 즉 **더 나은 질의가 존재할 수 있었다**
   (질의 생성의 문제).
3. **STRUCTURAL** — 출원 초록과 인용 문헌이 공유하는 실질 어휘가 2개
   미만이다. 초록만 입력으로 쓰는 한 어떤 질의 생성도 불가능하다
   (입력의 구조적 한계 — 심사관은 명세서 전문을 본다).

매치는 부분문자열 포함으로 근사한다 — KIPRIS 색인의 형태소 처리와 다를 수
있으므로 RANKED_OUT/QUERY_GAP 경계는 근사임을 감안하고 읽는다. IPC
서브클래스 일치는 별도 신호로 기록한다 (IPC 채널의 여지).

## 비용

인용 1건당 KIPRIS ≤2회(번호 해석 + 공보 상세, 캐시됨), 출원 1건당
Gemini 1회(질의 재추출 — 평가 당시 질의는 기록되지 않아 같은 설정으로
다시 뽑는 근사다).

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GCP_PROJECT_ID=... \
      GOLDEN_DIR=... .venv/Scripts/python scripts/diagnose_golden_misses.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from defusedxml.ElementTree import fromstring

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope

from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.patent.extraction import (
    TechnicalExtractor,
    expand_queries,
)
from ip_risk_agent.intelligence.patent.kipris import (
    ADVANCED_SEARCH_PATH,
    BASE_URL,
    DETAIL_PATH,
    normalize_application_number,
)
from ip_risk_agent.intelligence.patent.search_strategy import FIELDED_V1_PLAN

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
RAW_DIR = GOLDEN / "raw"
DIAG_DIR = ROOT / "labels" / "diagnosis"  # labels/ 는 gitignore

_STOPWORDS = {
    "있는", "있다", "하는", "하고", "하여", "위한", "위해", "따라", "따른",
    "대한", "대해", "및", "또는", "또한", "그리고", "본", "상기", "발명",
    "제공", "포함", "이용", "사용", "관한", "관련", "통해", "통한", "수",
    "것", "때", "등", "중", "더", "각", "이", "그", "저",
}


def _tokens(text: str) -> list[str]:
    """실질 어휘 근사 — 2글자 이상, 불용어 제외, 조사 제거는 하지 않는다."""
    words = re.findall(r"[가-힣A-Za-z]{2,}", text)
    return [w for w in words if w not in _STOPWORDS]


def _contains_all(words: list[str], text: str) -> bool:
    """KIPRIS AND 검색 근사 — 질의의 모든 단어가 본문에 부분문자열로 있다."""
    return all(word in text for word in words)


def _detail_xml(number: str, key: str, cache: Path) -> str:
    path = cache / f"biblio-{number}.xml"
    if not path.exists():
        response = httpx.get(
            f"{BASE_URL}/{DETAIL_PATH}",
            params={"applicationNumber": number, "ServiceKey": key},
            timeout=20.0,
        )
        response.raise_for_status()
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _resolve_citation(digits: str, key: str, cache: Path) -> str | None:
    """공보 번호 → 출원번호. getAdvancedSearch 의 번호 필드로 해석한다.

    13자리는 공개번호가 유력하고(실측: openNumber=1020080027504 →
    출원 1020060092598), 짧은 것은 등록번호다. 순서대로 시도한다.
    """
    path = cache / f"resolve-{digits}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("application_number")
    fields = (
        ("openNumber", "applicationNumber")
        if len(digits) >= 12
        else ("registerNumber",)
    )
    resolved = None
    for field in fields:
        response = httpx.get(
            f"{BASE_URL}/{ADVANCED_SEARCH_PATH}",
            params={
                field: digits,
                "patent": "true",
                "utility": "true",
                "docsStart": "1",
                "docsCount": "3",
                "ServiceKey": key,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        root = fromstring(response.text)
        item = next(root.iter("item"), None)
        if item is not None:
            resolved = normalize_application_number(
                item.findtext("applicationNumber") or ""
            )
            if resolved:
                break
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"citation": digits, "application_number": resolved}),
        encoding="utf-8",
    )
    return resolved


def _biblio_fields(xml_text: str) -> dict:
    root = fromstring(xml_text)
    title = ""
    summary = next(root.iter("biblioSummaryInfo"), None)
    if summary is not None:
        title = (summary.findtext("inventionTitle") or "").strip()
    abstract = ""
    for node in root.iter("astrtCont"):
        abstract = (node.text or "").strip()
        if abstract:
            break
    ipc = sorted(
        {
            (node.text or "").strip()[:4]
            for node in root.iter("ipcNumber")
            if (node.text or "").strip()
        }
    )
    return {"title": title, "abstract": abstract, "ipc_subclasses": ipc}


def _artifact(number: str, abstract: str) -> AnalysisArtifact:
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id=f"diagnosis:{number}",
        risk_workspace_id="golden-vws",
        mount_id="golden-mount",
        artifact_id=f"diagnosis:{number}",
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
            original_checksum=f"sha256:diagnosis-{number}",
            analysis_input_checksum=f"sha256:diagnosis-{number}",
        ),
        created_at=datetime.now(timezone.utc),
    )


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
        vertex_config={
            "vertexai": True,
            "project": project,
            "location": os.environ.get("VERTEX_LOCATION", "global"),
        },
    )


async def _queries_for(number: str, abstract: str, model, cache: Path) -> list[str]:
    """fielded_v1 설정(v3 프롬프트 + 확장)으로 질의 재추출. 캐시됨."""
    path = cache / f"queries-{number}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    extractor = TechnicalExtractor(
        model,
        prompt_name=FIELDED_V1_PLAN.extract_prompt,
        max_queries=FIELDED_V1_PLAN.max_queries,
    )
    extraction = await extractor.extract(_artifact(number, abstract))
    queries = expand_queries(extraction.search_queries)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    return queries


async def run(eval_dirname: str) -> int:
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 가 필요하다")
    model = _model_client()

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((GOLDEN / eval_dirname).glob("*.json"))
    ]
    records = [r for r in records if r.get("recall_misses")]
    if not records:
        raise SystemExit(f"{eval_dirname}/ 에 놓친 인용이 없다")

    rows = []
    counts = {"RANKED_OUT": 0, "QUERY_GAP": 0, "STRUCTURAL": 0, "UNRESOLVED": 0}
    for record in records:
        number = record["application_number"]
        source = _biblio_fields(_detail_xml(number, key, RAW_DIR))
        abstract = source["abstract"]
        if not abstract:
            print(f"  {number}: 출원 초록 없음 — 건너뜀")
            continue
        queries = await _queries_for(number, abstract, model, DIAG_DIR)
        source_vocab = set(_tokens(abstract))

        for citation in record["recall_misses"]:
            resolved = _resolve_citation(citation, key, DIAG_DIR)
            if not resolved:
                counts["UNRESOLVED"] += 1
                rows.append(
                    {
                        "application": number,
                        "citation": citation,
                        "category": "UNRESOLVED",
                    }
                )
                continue
            cited = _biblio_fields(_detail_xml(resolved, key, DIAG_DIR))
            cited_text = f"{cited['title']} {cited['abstract']}"
            title_hits = [
                q for q in queries if _contains_all(q.split(), cited["title"])
            ]
            abstract_hits = [
                q for q in queries if _contains_all(q.split(), cited["abstract"])
            ]
            shared = sorted(w for w in source_vocab if w in cited_text)
            if title_hits or abstract_hits:
                category = "RANKED_OUT"
            elif len(shared) >= 2:
                category = "QUERY_GAP"
            else:
                category = "STRUCTURAL"
            counts[category] += 1
            ipc_overlap = sorted(
                set(source["ipc_subclasses"]) & set(cited["ipc_subclasses"])
            )
            rows.append(
                {
                    "application": number,
                    "label": record["label"],
                    "citation": citation,
                    "cited_application": resolved,
                    "cited_title": cited["title"],
                    "category": category,
                    "title_hit_queries": title_hits,
                    "abstract_hit_queries": abstract_hits,
                    "shared_words": shared[:12],
                    "shared_count": len(shared),
                    "ipc_overlap": ipc_overlap,
                }
            )
            print(
                f"  {number} → {citation}: {category}"
                f" (공유어 {len(shared)} · IPC겹침 {','.join(ipc_overlap) or '-'}"
                f" · 제목매치질의 {len(title_hits)} · 초록매치질의 {len(abstract_hits)})"
            )

    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    (DIAG_DIR / "summary.json").write_text(
        json.dumps(
            {"eval_dir": eval_dirname, "counts": counts, "rows": rows},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    total = sum(counts.values())
    print(f"\n분류 (총 {total}건): " + " · ".join(f"{k} {v}" for k, v in counts.items()))
    ipc_share = sum(1 for r in rows if r.get("ipc_overlap"))
    print(f"IPC 서브클래스 겹침 있는 인용: {ipc_share}/{len(rows)}")
    print(f"세부 → {DIAG_DIR / 'summary.json'}")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", default="eval-plan-fielded_v1")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.eval_dir)))


if __name__ == "__main__":
    main()
