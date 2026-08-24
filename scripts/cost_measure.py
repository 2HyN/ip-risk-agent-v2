"""비용 측정 드라이버 — 배포 없이 로컬에서 분석 경로를 실호출로 태운다.

## 무엇을 하는가

``samples/`` 의 파일들을 License·Patent 분석 경로의 핵심 구간에 태워, 코드가 남기는
비용 이벤트(``gemini_usage`` · ``kipris_call`` · ``registry_call``)를 JSONL 파일로
받아 적는다. 같은 입력을 ``--runs`` 회 반복하면 2회차부터 인메모리 캐시가 받으므로
캐시 적중이 실측된다.

측정이 목적이므로 Firestore·Cloud Run·RAG corpus 없이 돈다. RAG 조항 검색은
이 드라이버의 범위 밖이다 — 그 부분은 팀 환경 배포 후 Cloud Logging 에서 잰다.

## 실행

    # 저장소 뿌리에서, venv 활성화 후
    export GEMINI_API_KEY=...        # AI Studio 발급 키 (없으면 Gemini 구간 생략)
    export KIPRIS_ACCESS_KEY=...     # KIPRIS Plus 키 (없으면 KIPRIS 구간 생략)
    python scripts/cost_measure.py --out cost-log.jsonl --runs 2

    # 모델 티어링 비교: 모델만 바꿔 같은 입력을 다시 돌린다
    python scripts/cost_measure.py --out cost-log.jsonl --model gemini-3.6-flash-lite

집계는 ``scripts/cost_report.py`` 가 한다.

## 키가 남긴 로그를 어떻게 줍는가

분석 코드는 ``logging`` 으로 한 줄 JSON 이벤트를 남긴다. 여기서는 ``ip_risk_agent``
로거에 핸들러 하나를 붙여, ``event`` 필드가 있는 줄만 실행 맥락(run·model)을 붙여
JSONL 로 저장한다. 분석 코드는 손대지 않는다 — 운영에서 Cloud Logging 이 하는
역할을 로컬에서 파일이 대신할 뿐이다.
"""

from __future__ import annotations

import _repo_path  # noqa: F401  -- 저장소 코드를 먼저 경로에 올린다

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient, PromptLibrary
from ip_risk_agent.intelligence.gemini.schemas import PatentComparison, TechnicalExtraction
from ip_risk_agent.intelligence.license.dependency_models import DependencyDeclaration
from ip_risk_agent.intelligence.license.manifests import (
    parse_package_json,
    parse_requirements_txt,
)
from ip_risk_agent.intelligence.license.package_metadata import HttpPackageMetadataProvider
from ip_risk_agent.intelligence.license.policy import evaluate_expression
from ip_risk_agent.intelligence.patent.cache import (
    CachingPatentSearchProvider,
    InMemoryPatentResponseCache,
)
from ip_risk_agent.intelligence.patent.kipris import KiprisClient

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = REPO_ROOT / "samples"

# 문서가 아주 길면 추출 프롬프트가 통제 없이 커진다. 운영은 segment 로 자르지만
# 여기서는 측정 단위를 고정하기 위해 상한을 둔다. 값은 인자로 바꿀 수 있다.
DEFAULT_DOC_CHARS = 6000

# 표본 5편에서는 문제없었으나 30편으로 늘리자 연속 호출이 쌓여 KIPRIS 쪽에서
# ProviderFailureError(레이트리밋으로 추정)가 다발했다. 호출 사이 최소 간격.
KIPRIS_THROTTLE_SECONDS = 0.5


class CompareLogWriter:
    """PatentComparison 의 실제 내용을 모델·문서별로 남긴다.

    비용 이벤트(``JsonlCapture``)는 개수만 세지 내용을 담지 않는다 — 원문 유출
    방지 원칙을 드라이버에서도 지킨다. 그런데 모델 티어링은 "싸다"만으로는
    답이 안 되고 "품질이 유지되는가"가 있어야 결론이 된다. 그 판단 재료가 이
    파일이다. 이 파일은 로그가 아니라 사람이 검토할 산출물이므로 남긴다 —
    운영 코드 원칙과는 다른 목적이다.
    """

    def __init__(self, path: Path, *, model: str) -> None:
        self._file = path.open("a", encoding="utf-8")
        self._model = model

    def write(self, *, doc: str, application_number: str, query: str, comparison) -> None:
        record = {
            "model": self._model,
            "doc": doc,
            "application_number": application_number,
            "query": query,
            "matched_elements": [
                {
                    "explanation": m.explanation,
                    "source_quote": m.source_quote,
                    "patent_quote": m.patent_quote,
                }
                for m in comparison.matched_elements
            ],
            "distinct_elements": comparison.distinct_elements,
            "review_caveats": comparison.review_caveats,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class JsonlCapture(logging.Handler):
    """``event`` 필드를 가진 한 줄 JSON 로그만 골라 JSONL 로 저장한다."""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.INFO)
        self._file = path.open("a", encoding="utf-8")
        self.context: dict[str, object] = {}
        self.counts: dict[str, int] = {}

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or "event" not in payload:
            return
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        payload.update(self.context)
        self._file.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        self._file.flush()
        event = str(payload["event"])
        self.counts[event] = self.counts.get(event, 0) + 1

    def close(self) -> None:  # noqa: D102
        self._file.close()
        super().close()


def _load_license_declarations(max_deps: int) -> list[DependencyDeclaration]:
    declarations: list[DependencyDeclaration] = []
    requirements = SAMPLES / "license" / "requirements.txt"
    package_json = SAMPLES / "license" / "package.json"
    if requirements.is_file():
        declarations += parse_requirements_txt(
            requirements.read_text(encoding="utf-8"), str(requirements)
        )
    if package_json.is_file():
        declarations += parse_package_json(
            package_json.read_text(encoding="utf-8"), str(package_json)
        )
    resolved = [d for d in declarations if d.version is not None]
    return resolved[:max_deps]


async def _run_license(max_deps: int) -> None:
    declarations = _load_license_declarations(max_deps)
    if not declarations:
        print("  license: 샘플에서 버전이 확정된 의존성을 찾지 못해 생략")
        return
    async with HttpPackageMetadataProvider() as provider:
        for declaration in declarations:
            try:
                fact = await provider.get_license(
                    declaration.ecosystem, declaration.name, declaration.version
                )
            except Exception as exc:  # noqa: BLE001 - 측정은 계속한다
                print(f"  license: {declaration.name} 조회 실패 ({type(exc).__name__})")
                continue
            outcome = evaluate_expression(fact.license_expression)
            print(
                f"  license: {declaration.name}=={declaration.version}"
                f" → {fact.license_expression} [{outcome.value}] ({fact.source})"
            )


async def _run_patent(
    gemini: GoogleGenAIClient | None,
    kipris: CachingPatentSearchProvider | None,
    prompts: PromptLibrary,
    max_docs: int,
    max_queries: int,
    rows: int,
    doc_chars: int,
    compare_log: "CompareLogWriter | None" = None,
) -> None:
    if gemini is None:
        print("  patent: GEMINI_API_KEY 없음 — 구간 생략")
        return
    docs = sorted((SAMPLES / "patent").glob("*.md"))[:max_docs]
    extract_prompt = prompts.get("patent_extract_v2")
    compare_prompt = prompts.get("patent_compare_v2")
    for doc in docs:
        text = doc.read_text(encoding="utf-8")[:doc_chars]
        segments = f"[seg-1]\n{text}"
        extraction = await gemini.generate(
            extract_prompt.render(segments=segments), TechnicalExtraction
        )
        print(
            f"  patent: {doc.name} → is_technical={extraction.is_technical},"
            f" queries={len(extraction.search_queries)}"
        )
        if not extraction.is_technical or kipris is None:
            continue
        for query in extraction.search_queries[:max_queries]:
            # 표본을 30편으로 늘리면서 문서당 최대 max_queries회씩 연속 호출이
            # 쌓여 KIPRIS 쪽에서 ProviderFailureError(레이트리밋으로 추정)가
            # 다발했다 — 호출 사이에 짧은 간격을 둬 부담을 낮춘다.
            await asyncio.sleep(KIPRIS_THROTTLE_SECONDS)
            try:
                hits = await kipris.search(query, rows=rows)
            except Exception as exc:  # noqa: BLE001
                print(f"    kipris 검색 실패 ({type(exc).__name__})")
                continue
            if not hits:
                continue
            await asyncio.sleep(KIPRIS_THROTTLE_SECONDS)
            try:
                document = await kipris.fetch_detail(hits[0].application_number)
            except Exception as exc:  # noqa: BLE001
                print(f"    kipris 상세 실패 ({type(exc).__name__})")
                continue
            if not document.abstract:
                continue
            evidence = (
                f"[patent-1] 출원번호 {document.application_number}\n"
                f"제목: {document.title}\n초록: {document.abstract}"
            )
            comparison = await gemini.generate(
                compare_prompt.render(segments=segments, patent_evidence=evidence),
                PatentComparison,
            )
            print(
                f"    compare 완료: {document.application_number}"
                f" (matched={len(comparison.matched_elements)},"
                f" distinct={len(comparison.distinct_elements)},"
                f" caveats={len(comparison.review_caveats)})"
            )
            if compare_log is not None:
                compare_log.write(
                    doc=doc.name,
                    application_number=document.application_number,
                    query=query,
                    comparison=comparison,
                )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", default="cost-log.jsonl", help="이벤트 JSONL 출력 경로")
    parser.add_argument("--runs", type=int, default=2, help="반복 횟수 (2회부터 캐시 적중 측정)")
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL_ID", "gemini-3.6-flash"))
    parser.add_argument("--max-deps", type=int, default=10)
    parser.add_argument("--max-docs", type=int, default=2)
    parser.add_argument("--max-queries", type=int, default=2)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--doc-chars", type=int, default=DEFAULT_DOC_CHARS)
    parser.add_argument("--skip-license", action="store_true")
    parser.add_argument("--skip-patent", action="store_true")
    parser.add_argument(
        "--compare-out", default="compare-results.jsonl",
        help="PatentComparison 내용(matched/distinct/caveats) 저장 경로 — 품질 비교용",
    )
    args = parser.parse_args()

    capture = JsonlCapture(Path(args.out))
    logging.getLogger("ip_risk_agent").addHandler(capture)
    logging.getLogger("ip_risk_agent").setLevel(logging.INFO)

    compare_log = CompareLogWriter(Path(args.compare_out), model=args.model)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    kipris_key = os.environ.get("KIPRIS_ACCESS_KEY", "")
    gemini = GoogleGenAIClient(args.model, api_key=gemini_key) if gemini_key else None
    kipris_client = KiprisClient(kipris_key) if kipris_key else None
    # 캐시는 실행 전체에서 하나를 공유해야 2회차의 적중이 측정된다.
    kipris = (
        CachingPatentSearchProvider(kipris_client, InMemoryPatentResponseCache())
        if kipris_client is not None
        else None
    )
    prompts = PromptLibrary()

    try:
        for run in range(1, args.runs + 1):
            capture.context = {"run": run, "run_model": args.model}
            print(f"== run {run}/{args.runs} (model={args.model}) ==")
            if not args.skip_license:
                await _run_license(args.max_deps)
            if not args.skip_patent:
                await _run_patent(
                    gemini, kipris, prompts,
                    args.max_docs, args.max_queries, args.rows, args.doc_chars,
                    compare_log=compare_log,
                )
    finally:
        if kipris is not None:
            await kipris.aclose()
        capture.close()
        compare_log.close()

    print("\n수집된 이벤트:", json.dumps(capture.counts, ensure_ascii=False, sort_keys=True))
    print(f"로그 파일: {args.out} — 집계는 python scripts/cost_report.py {args.out}")
    print(f"대조 결과: {args.compare_out} — 모델별 matched/distinct/caveats 원문 비교용")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
