"""골든셋 평가 — 수집한 심사 이력에 실제 파이프라인을 돌려 잰다.

## 무엇을 재는가

``collect_golden_pairs.py`` 가 만든 (출원 초록, 심사 결과 라벨) 쌍마다 운영과
같은 ``PatentAnalyzer`` 를 **라이브 KIPRIS** 로 돌리고 두 가지를 기록한다.

1. **recall** — 심사관이 통지서에 첨부한 선행문헌을 우리 후보 6개가 포함하는가
2. **등급·점수** — suggested_review_priority 와 evidence_strength 가 라벨
   (0 일발등록 · 1 극복 · 2 거절)과 어떤 관계인가

라이브로 도는 이유: recall 은 "실제 KIPRIS 색인 전체에서 그 문헌을 찾아오는가"
가 질문이라 고정 코퍼스로 재면 자기 채점이 된다.

## 번호 체계 — 대조의 함정

심사관 인용은 **공보 번호**이고 후보는 **출원번호**다. 둘은 다른 체계다.

* 공개특허공보 10-YYYY-NNNNNNN → 숫자만 남기면 13자리, 출원번호와 같은 모양
  이라 직접 대조한다
* 등록특허공보 10-NNNNNNN → 9~10자리, 출원번호와 무관하다. 후보 출원의 공보
  상세(캐시 우선)에서 registerNumber 를 얻어 대조한다 — 후보당 최대 1회 추가

## 비용

건당 KIPRIS 약 11회(검색 5 + 상세 6) + 등록번호 대조 최대 6회, Gemini 약 7회.
``--limit`` (기본 3) 으로 소규모 스모크부터 돌린다. 응답·결과는 전부
``labels/golden/eval/`` 에 남고, 이미 평가한 출원은 건너뛴다.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GEMINI_API_KEY=... \
      .venv/Scripts/python scripts/evaluate_golden.py --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.kipris import (
    BASE_URL,
    DETAIL_PATH,
    KiprisClient,
    normalize_application_number,
)
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket
from ip_risk_agent.intelligence.patent.search_strategy import plan_for

ROOT = Path(__file__).resolve().parents[1]
# 골든셋이 저장소 밖(팀 공유 폴더)에 있으면 GOLDEN_DIR 로 가리킨다.
# 기본값은 수집 스크립트의 산출 위치 그대로다.
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
RAW_DIR = GOLDEN / "raw"
EVAL_DIR = GOLDEN / "eval"


def _abstract_of(number: str) -> str | None:
    """collect 가 캐시한 공보 XML 에서 초록을 꺼낸다. 추가 호출 없음."""
    path = RAW_DIR / f"biblio-{number}.xml"
    if not path.exists():
        return None
    root = fromstring(path.read_text(encoding="utf-8"))
    node = next(root.iter("astrtCont"), None)
    text = (node.text or "").strip() if node is not None else ""
    return text or None


def _register_number_of(number: str, key: str) -> str:
    """후보 출원의 등록번호. 캐시가 있으면 공짜, 없으면 1회 조회 후 캐시."""
    path = RAW_DIR / f"biblio-{number}.xml"
    if not path.exists():
        response = httpx.get(
            f"{BASE_URL}/{DETAIL_PATH}",
            params={"applicationNumber": number, "ServiceKey": key},
            timeout=20.0,
        )
        response.raise_for_status()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
    root = fromstring(path.read_text(encoding="utf-8"))
    node = next(root.iter("registerNumber"), None)
    return normalize_application_number((node.text or "") if node is not None else "")


def _artifact(number: str, abstract: str) -> AnalysisArtifact:
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id=f"golden:{number}",
        risk_workspace_id="golden-vws",
        mount_id="golden-mount",
        artifact_id=f"golden-artifact:{number}",
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
            original_checksum=f"sha256:golden-{number}",
            analysis_input_checksum=f"sha256:golden-{number}",
        ),
        created_at=datetime.now(timezone.utc),
    )


def _match_citations(
    cited: list[str], candidate_numbers: list[str], key: str
) -> dict:
    """심사관 인용 ↔ 후보 대조. 공개형은 직접, 등록형은 등록번호로."""
    candidate_registers: dict[str, str] | None = None
    hits, misses = [], []
    for citation in cited:
        digits = normalize_application_number(citation)
        if len(digits) >= 12:
            (hits if digits in candidate_numbers else misses).append(digits)
            continue
        # 등록공보 번호 — 후보들의 등록번호와 대조 (필요할 때 한 번만 수집)
        if candidate_registers is None:
            candidate_registers = {
                _register_number_of(number, key): number
                for number in candidate_numbers
            }
            candidate_registers.pop("", None)
        (hits if digits in candidate_registers else misses).append(digits)
    return {"hits": hits, "misses": misses}


def _application_date_of(number: str) -> str | None:
    """출원일(YYYYMMDD). 개선 모드의 선행기술 컷오프로 쓴다."""
    path = RAW_DIR / f"biblio-{number}.xml"
    if not path.exists():
        return None
    root = fromstring(path.read_text(encoding="utf-8"))
    node = next(root.iter("applicationDate"), None)
    digits = (
        "".join(ch for ch in (node.text or "") if ch.isdigit())
        if node is not None
        else ""
    )
    return digits[:8] or None


def _model_client() -> GoogleGenAIClient:
    """Gemini 클라이언트. API 키가 없으면 Vertex(ADC) 로 폴백한다."""
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


async def run(
    limit: int,
    labels: set[int],
    *,
    improved: bool = False,
    expand: bool = False,
    fielded: bool = False,
    cited_only: bool = False,
    search_strategy: str | None = None,
    compare_strategy: str = "baseline",
) -> int:
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 가 필요하다")

    rows = [
        json.loads(line)
        for line in (GOLDEN / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 개선 조합마다 별도 폴더 — before / 필터+풀 / +질의확장을 나란히 비교한다.
    suffix = "eval"
    if improved:
        suffix = "eval-improved-expand" if expand else "eval-improved"
    if fielded:
        suffix = "eval-fielded-expand" if expand else "eval-fielded"
    # 전략 프리셋 모드 — 개별 플래그 대신 SearchPlan 이 손잡이를 정한다.
    plan = plan_for(search_strategy) if search_strategy else None
    if plan is not None:
        suffix = f"eval-plan-{plan.name}"
        if compare_strategy == "rag":
            suffix += "-rag"
    out_dir = GOLDEN / suffix
    out_dir.mkdir(parents=True, exist_ok=True)

    max_rps = os.environ.get("KIPRIS_MAX_RPS", "").strip()
    kipris = KiprisClient(
        access_key=key,
        # 항목별검색 — 제목(정밀) 먼저, 초록(재현) 으로 보강. 전략 프리셋
        # 모드에서는 계획이 채널을 정한다.
        search_fields=(
            plan.search_fields
            if plan is not None
            else (("inventionTitle", "astrtCont") if fielded else None)
        ),
        rate_limiter=TokenBucket(float(max_rps)) if max_rps else None,
    )
    model = _model_client()

    done = 0
    try:
        for row in rows:
            if done >= limit:
                break
            if row["label"] not in labels:
                continue
            if cited_only and not row.get("examiner_cited"):
                continue
            number = row["application_number"]
            out = out_dir / f"{number}.json"
            if out.exists():
                continue  # 이미 평가함 — 재실행은 남은 것만 돈다
            abstract = _abstract_of(number)
            if abstract is None:
                print(f"  {number}: 초록 없음 — 건너뜀")
                continue
            # 개선 모드: 그 출원의 출원일을 컷오프로, 검색 풀 20건.
            # 기본 모드: 운영과 동일 (컷오프 없음, 5건).
            # 전략 프리셋 모드: 계획이 손잡이를 정하고, 컷오프는 항상 켠다 —
            # 평가에서는 출원일 이후 문서가 정의상 선행기술이 아니기 때문.
            if plan is not None:
                analyzer = PatentAnalyzer(
                    kipris,
                    model,
                    candidate_cap=6,
                    search_plan=plan,
                    compare_strategy=compare_strategy,
                    prior_art_cutoff=_application_date_of(number),
                    # 자기 초록으로 검색하면 자기 출원이 1위로 걸린다 —
                    # 평가에서는 정의상 후보가 아니므로 제외한다.
                    exclude_application_numbers=(number,),
                )
            else:
                analyzer = PatentAnalyzer(
                    kipris,
                    model,
                    candidate_cap=6,
                    prior_art_cutoff=(
                        _application_date_of(number) if improved else None
                    ),
                    search_rows=20 if improved else 5,
                    query_expansion=expand,
                )
            result = await analyzer.analyze(_artifact(number, abstract))
            candidates = [
                {
                    "application_number": c.normalized_application_number,
                    "priority": c.suggested_review_priority.value,
                    "matched": len(c.matched_elements),
                    "strength": c.provider_metadata_safe.get("evidence_strength"),
                }
                for c in result.candidates
            ]
            recall = _match_citations(
                row.get("examiner_cited") or [],
                [c["application_number"] for c in candidates],
                key,
            )
            record = {
                "application_number": number,
                "label": row["label"],
                "condition": suffix,
                "status": result.status.value,
                "candidates": candidates,
                "examiner_cited": row.get("examiner_cited") or [],
                "recall_hits": recall["hits"],
                "recall_misses": recall["misses"],
                "failures": [
                    f"{f.provider}/{f.category}" for f in result.provider_failures
                ],
            }
            out.write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            top = max(
                (c["strength"] or "0" for c in candidates), default=None
            )
            print(
                f"  {number}: label={row['label']} status={record['status']}"
                f" 후보={len(candidates)} recall={len(recall['hits'])}/"
                f"{len(recall['hits']) + len(recall['misses'])} top강도={top}"
            )
            done += 1
    finally:
        await kipris.aclose()
    print(f"\n평가 {done}건 → {out_dir}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--labels", type=int, nargs="*", default=[0, 1, 2],
        help="이 라벨의 건만 평가",
    )
    parser.add_argument("--improved", action="store_true",
                        help="개선판(출원일 컷오프+검색 풀 20) - eval-improved/")
    parser.add_argument("--cited-only", action="store_true",
                        help="심사관 인용 있는 건만 (recall 재측정)")
    parser.add_argument("--expand", action="store_true",
                        help="질의 확장까지 켬 (improved 와 함께) - eval-improved-expand/")
    parser.add_argument("--fielded", action="store_true",
                        help="항목별검색(제목+초록) - eval-fielded/")
    parser.add_argument("--search-strategy",
                        choices=("baseline", "expanded_v1", "fielded_v1", "fielded_v2", "fielded_v3", "fielded_v4"),
                        default=None,
                        help="SearchPlan 프리셋으로 평가 (개별 플래그 대신) "
                             "- eval-plan-<이름>[-rag]/")
    parser.add_argument("--compare-strategy", choices=("baseline", "rag"),
                        default="baseline",
                        help="--search-strategy 와 함께 쓰는 대조 전략")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.limit, set(args.labels),
                             improved=args.improved, expand=args.expand,
                             fielded=args.fielded,
                             cited_only=args.cited_only,
                             search_strategy=args.search_strategy,
                             compare_strategy=args.compare_strategy)))


if __name__ == "__main__":
    main()
