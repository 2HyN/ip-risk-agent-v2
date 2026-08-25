"""검색 층 recall — 대조를 빼고 검색·순위만 잰다.

## 왜 따로 만드는가

``evaluate_golden.py`` 의 recall 은 ``result.candidates`` 로 세는데, 분석기는
**대조에서 매칭이 나온 후보만** 그 목록에 담는다. 그래서 그 숫자는 검색 recall 이
아니라 `검색 ∩ 순위 ∩ 대조` 다. 검색 전략을 A/B 하는 데 그것을 쓰면, 우리가
바꾸지 않은 층(대조 프롬프트·모델의 그날 기분)의 변덕이 판정에 섞인다.

E2-4 가 고정 풀 ablation 으로 옮겨 간 이유가 이것이었다. 다만 고정 풀은 **질의가
같을 때만** 쓸 수 있고, 이번 변경은 질의 자체를 바꾼다. 그래서 검색은 라이브로
돌리되 **대조는 돌리지 않는다.** 출원당 Gemini 호출은 추출 1회뿐이고, 그것도
캐시된다.

## 무엇을 세는가

심사관 인용이 어디까지 살아 오는지를 세 지점에서 가른다.

* ``pool`` — 검색이 데려온 전체 후보(중복 병합 후)에 있는가. **검색 폭.**
* ``judged`` — 순위·정밀꼬리가 고른 판정 대상에 있는가. **검색 + 순위.**
* 못 왔으면 어디서 죽었는지가 자동으로 갈린다 (풀에 없으면 검색 탓, 풀에는
  있는데 판정 대상에 없으면 순위 탓).

부수로 **질의당 결과집합 크기**를 남긴다 — 안 1 의 선행지표다.

## 결정론

질의는 출원·전략마다 1회 추출해 캐시한다. 추출은 모델이 하므로 캐시하지 않으면
실행마다 풀이 달라져 A/B 가 성립하지 않는다 (E2-2 의 교란 발견).

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GEMINI_API_KEY=... \
      GOLDEN_DIR=... KIPRIS_MAX_RPS=1.4 \
      python scripts/evaluate_search_recall.py --search-strategy fielded_v4
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from defusedxml.ElementTree import fromstring

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope

from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.patent.candidate_rank import (
    rank_candidates,
    rank_candidates_bm25,
    rank_candidates_rrf,
)
from ip_risk_agent.intelligence.patent.ephemeral_index import tokenize
from ip_risk_agent.intelligence.patent.extraction import (
    TechnicalExtractor,
    expand_queries,
    query_families,
)
from ip_risk_agent.intelligence.patent.kipris import KiprisClient, PatentSearchHit
from ip_risk_agent.intelligence.patent.query_builder import run_searches
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket
from ip_risk_agent.intelligence.patent.search_strategy import plan_for

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
RAW_DIR = GOLDEN / "raw"
OUT_ROOT = ROOT / "labels" / "search-recall"
#: probe_query_ceiling.py 가 이미 인용 번호 -> 출원번호를 전부 해석해 뒀다.
#: 같은 캐시를 읽어 KIPRIS 호출을 0 회로 만든다.
RESOLVE_CACHE = ROOT / "labels" / "query-ceiling"
#: 검색 응답 캐시. 질의·필드·rows 가 같으면 KIPRIS 를 다시 부르지 않는다.
SEARCH_CACHE = ROOT / "labels" / "search-cache"

#: **클라이언트의 검색 동작 판(版).** 요청을 만드는 방식이 바뀌면 반드시
#: 올린다 — 안 올리면 옛 동작으로 받은 응답을 새 동작의 결과로 오독한다.
#: 지금 값은 b68dd2d 기준이다: `*` AND 조인 + 필드 병합 무절단. 그 이전
#: (공백 조인·merged[:rows]) 응답과 섞이면 안 되므로 판이 다르다.
CLIENT_REV = "and-star+nomergecap"


class CachedSearch:
    """KiprisClient 를 감싸 검색 응답을 디스크에 남긴다.

    KIPRIS 는 공용 키의 0.7초 간격이 하한이라 수집이 벽시계를 지배한다.
    그런데 이 하네스가 답하는 질문(임계값·순위 변형)은 **같은 풀 위에서**
    반복 채점하는 성질이다. 한 번 받아 두면 재채점이 공짜가 된다 —
    E2-4 가 고정 풀 ablation 으로 옮겨 간 것과 같은 이유다.
    """

    def __init__(self, inner: KiprisClient, fields, cache: Path) -> None:
        self._inner = inner
        self._tag = CLIENT_REV + "|" + ",".join(fields or ())
        self._cache = cache
        self.hits = 0
        self.misses = 0

    def _path(self, query: str, rows: int) -> Path:
        digest = hashlib.sha1(
            f"{self._tag}|{query}|{rows}".encode()
        ).hexdigest()[:16]
        return self._cache / f"s-{digest}.json"

    async def search(self, query: str, *, rows: int = 5):
        path = self._path(query, rows)
        if path.exists():
            self.hits += 1
            return [
                PatentSearchHit(
                    application_number=row["n"],
                    title=row["t"],
                    query=query,
                    metadata=row["m"],
                    abstract=row["a"],
                )
                for row in json.loads(path.read_text(encoding="utf-8"))
            ]
        found = await self._inner.search(query, rows=rows)
        self.misses += 1
        self._cache.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [
                    {
                        "n": hit.application_number,
                        "t": hit.title,
                        "m": hit.metadata,
                        "a": hit.abstract,
                    }
                    for hit in found
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return found

    async def aclose(self) -> None:
        await self._inner.aclose()


def _text(path: Path, tag: str) -> str:
    for node in fromstring(path.read_text(encoding="utf-8")).iter(tag):
        if (node.text or "").strip():
            return (node.text or "").strip()
    return ""


def _abstract_of(number: str) -> str:
    path = RAW_DIR / f"biblio-{number}.xml"
    return _text(path, "astrtCont") if path.exists() else ""


def _application_date_of(number: str) -> str | None:
    path = RAW_DIR / f"biblio-{number}.xml"
    if not path.exists():
        return None
    return re.sub(r"\D", "", _text(path, "applicationDate")) or None


def _resolved_citations() -> dict[str, str]:
    """인용 공보번호 -> 출원번호. 캐시가 없으면 그 인용은 원번호로 대조한다."""
    table: dict[str, str] = {}
    for path in RESOLVE_CACHE.glob("resolve-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        resolved = payload.get("application_number")
        if resolved:
            table[str(payload["citation"])] = resolved
    return table


def _artifact(number: str, abstract: str) -> AnalysisArtifact:
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id=f"searchrecall:{number}",
        risk_workspace_id="golden-vws",
        mount_id="golden-mount",
        artifact_id=f"searchrecall:{number}",
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
            original_checksum=f"sha256:sr-{number}",
            analysis_input_checksum=f"sha256:sr-{number}",
        ),
        created_at=datetime.now(timezone.utc),
    )


def _model_client() -> GoogleGenAIClient:
    model_id = os.environ.get("GEMINI_MODEL_ID") or os.environ.get(
        "GEMINI_MODEL", "gemini-3-flash-preview"
    )
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key:
        return GoogleGenAIClient(model_id, api_key=api_key)
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


async def _queries_for(number, abstract, plan, model, cache: Path) -> list[str]:
    """전략의 추출 프롬프트로 질의를 뽑는다. 출원·전략마다 1회, 이후 캐시."""
    path = cache / f"queries-{number}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    extractor = TechnicalExtractor(
        model, prompt_name=plan.extract_prompt, max_queries=plan.max_queries
    )
    extraction = await extractor.extract(_artifact(number, abstract))
    queries = list(extraction.search_queries)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    return queries


def _select(plan, outcome, originals, executed, abstract, exclude):
    """운영과 같은 순위 기계로 판정 대상을 고른다."""
    families = query_families(originals, executed)
    source_tokens = frozenset(tokenize(abstract))
    if plan.use_bm25:
        return rank_candidates_bm25(
            outcome.hits_by_query,
            source_tokens=source_tokens,
            cap=plan.compare_cap,
            family_of=families,
            exclude=exclude,
            judge_tail_to=plan.judge_tail_to,
            judge_tail_total_cap=plan.judge_tail_total_cap,
        )
    if plan.use_rrf:
        return rank_candidates_rrf(
            outcome.hits_by_query,
            cap=plan.compare_cap,
            family_of=families,
            source_tokens=source_tokens,
            exclude=exclude,
        )
    return rank_candidates(outcome.hits_by_query, cap=plan.compare_cap)


async def run(args) -> int:
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 가 필요하다")
    plan = plan_for(args.search_strategy)
    # 모델을 바꿔 재면 질의가 달라지므로 결과가 섞이면 안 된다. 태그로 가른다.
    out_dir = OUT_ROOT / (
        f"{plan.name}@{args.model_tag}" if args.model_tag else plan.name
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    records = [
        json.loads(line)
        for line in (GOLDEN / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [r for r in records if r.get("examiner_cited")][: args.limit or None]
    resolved = _resolved_citations()
    print(f"{plan.name}: 출원 {len(records)}건 · 인용 해석 캐시 {len(resolved)}건")

    max_rps = os.environ.get("KIPRIS_MAX_RPS", "").strip()
    kipris = CachedSearch(
        KiprisClient(
            access_key=key,
            search_fields=plan.search_fields,
            rate_limiter=TokenBucket(float(max_rps)) if max_rps else None,
        ),
        plan.search_fields,
        SEARCH_CACHE,
    )
    model = _model_client()

    # 질의 추출을 먼저 몰아서 끝낸다 — Gemini 는 KIPRIS 의 초당 제한과 무관하니
    # 병렬로 돌리고, 그 다음 검색만 직렬로 흘린다. 캐시가 차 있으면 즉시 끝난다.
    pending = [
        record
        for record in records
        if not (out_dir / f"{record['application_number']}.json").exists()
        and _abstract_of(record["application_number"])
    ]
    if pending:
        gate = asyncio.Semaphore(5)

        async def _prefetch(record):
            number = record["application_number"]
            async with gate:
                try:
                    await _queries_for(
                        number, _abstract_of(number), plan, model, out_dir
                    )
                except Exception as error:  # noqa: BLE001 -- 1건 실패가 전체를 막지 않는다
                    print(f"  {number}: 질의 추출 실패 {type(error).__name__}")

        await asyncio.gather(*(_prefetch(record) for record in pending))
        print(f"질의 추출 완료 ({len(pending)}건) — 이제 검색만 남는다\n")

    totals = Counter()
    query_widths: list[int] = []
    try:
        for record in records:
            number = record["application_number"]
            out = out_dir / f"{number}.json"
            if out.exists():
                payload = json.loads(out.read_text(encoding="utf-8"))
                totals["cited"] += len(payload["cited"])
                totals["pool"] += len(payload["in_pool"])
                totals["judged"] += len(payload["in_judged"])
                query_widths.extend(payload.get("result_sizes", []))
                continue
            abstract = _abstract_of(number)
            if not abstract:
                print(f"  {number}: 초록 없음 — 건너뜀")
                continue

            originals = await _queries_for(number, abstract, plan, model, out_dir)
            executed = expand_queries(originals) if plan.expand_queries else originals
            if not executed:
                print(f"  {number}: 질의 0개 — 건너뜀")
                continue

            outcome = await run_searches(
                kipris,
                executed,
                rows=plan.rows,
                relax_zero_hits=plan.relax_zero_hits,
                stage_deadline_seconds=None,  # 평가는 마감으로 자르지 않는다
            )
            cutoff = _application_date_of(number)
            if cutoff:
                from ip_risk_agent.intelligence.patent.analyzer import _drop_future_hits

                _drop_future_hits(outcome.hits_by_query, cutoff)

            pool = {
                hit.application_number
                for hits in outcome.hits_by_query.values()
                for hit in hits
            } - {number}
            selected = _select(
                plan, outcome, originals, executed, abstract, frozenset({number})
            )
            judged = {c.application_number for c in selected}

            cited = [resolved.get(str(c), str(c)) for c in record["examiner_cited"]]
            cited = [c for c in cited if c != number]  # 자기 인용 제외
            in_pool = [c for c in cited if c in pool]
            in_judged = [c for c in cited if c in judged]

            sizes = sorted(
                int(hit.metadata["search_total"])
                for hits in outcome.hits_by_query.values()
                for hit in hits[:1]
                if hit.metadata.get("search_total", "").isdigit()
            )
            payload = {
                "application_number": number,
                "strategy": plan.name,
                "label": record["label"],
                "queries": originals,
                "executed_queries": len(executed),
                "zero_hit_queries": outcome.zero_hit_queries,
                "relaxed": len(outcome.relaxations),
                "relax_recovered": outcome.relax_recovered,
                "pool_size": len(pool),
                "judged_size": len(judged),
                "cited": cited,
                "in_pool": in_pool,
                "in_judged": in_judged,
                "result_sizes": sizes,
                "failures": len(outcome.failures),
            }
            out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            totals["cited"] += len(cited)
            totals["pool"] += len(in_pool)
            totals["judged"] += len(in_judged)
            query_widths.extend(sizes)
            print(
                f"  {number}: 질의 {len(executed)} · 풀 {len(pool):4}"
                f" · 판정 {len(judged):2} · 인용 {len(in_pool)}/{len(cited)} 풀"
                f" → {len(in_judged)}/{len(cited)} 판정"
            )
    finally:
        await kipris.aclose()

    print(f"\n{'='*58}\n{plan.name} — 인용 {totals['cited']}건\n{'='*58}")
    for stage in ("pool", "judged"):
        share = totals[stage] / totals["cited"] * 100 if totals["cited"] else 0
        label = "풀 진입 (검색 폭)" if stage == "pool" else "판정 대상 (검색+순위)"
        print(f"  {label:24} {totals[stage]:3}/{totals['cited']}  ({share:4.1f}%)")
    if query_widths:
        print(
            f"\n  질의당 결과집합 중앙값 {statistics.median(query_widths):,.0f}"
            f" · 30건 이하 {sum(1 for w in query_widths if w <= 30)}/{len(query_widths)}"
            f" · 300건 초과 {sum(1 for w in query_widths if w > 300)}/{len(query_widths)}"
        )
    print(
        f"\n  검색 캐시 적중 {kipris.hits} · 신규 호출 {kipris.misses}"
        f" (클라이언트 판 {CLIENT_REV})"
    )
    print(f"\n세부 -> {out_dir}")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-strategy", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model-tag", default="",
                        help="출력 폴더를 모델별로 가른다 (질의 캐시도 분리된다)")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
