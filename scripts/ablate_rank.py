"""순위 신호 ablation — 같은 검색 풀 위에서 순위 변형만 바꿔 잰다.

## 왜 오프라인인가

evaluate_golden 은 실행마다 Gemini 가 질의를 다시 뽑아 검색 풀 자체가
달라진다 — 순위 변경의 효과가 질의 비결정성에 묻힌다 (실측: 같은 출원이
한 실행에서 후보 5건, 다음 실행에서 0건). 여기서는 출원당 질의와 풀을
**한 번만** 수집해 캐시하고, 같은 풀 위에서 순위 변형을 바꿔 가며
"심사관 인용이 top-cap 에 드는가"를 잰다. 대조(Gemini)는 부르지 않는다 —
이 지표는 검색+순위 층만 본다.

질의는 diagnose_golden_misses.py 가 캐시한 것(fielded_v1 설정 재추출)을
재사용하고, 없으면 새로 뽑아 같은 곳에 캐시한다.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GCP_PROJECT_ID=... \
      GOLDEN_DIR=... .venv/Scripts/python scripts/ablate_rank.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from defusedxml.ElementTree import fromstring

from ip_risk_agent.intelligence.patent.candidate_rank import (
    rank_candidates,
    rank_candidates_rrf,
)
from ip_risk_agent.intelligence.patent.ephemeral_index import tokenize
from ip_risk_agent.intelligence.patent.extraction import query_families
from ip_risk_agent.intelligence.patent.kipris import (
    KiprisClient,
    PatentSearchHit,
    normalize_application_number,
)
from ip_risk_agent.intelligence.patent.rate_limit import TokenBucket

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
RAW_DIR = GOLDEN / "raw"
DIAG_DIR = ROOT / "labels" / "diagnosis"
POOL_DIR = ROOT / "labels" / "rank-ablation"

CAP = 8


def _biblio_text(number: str, tag: str) -> str:
    path = RAW_DIR / f"biblio-{number}.xml"
    if not path.exists():
        return ""
    root = fromstring(path.read_text(encoding="utf-8"))
    node = next(root.iter(tag), None)
    return (node.text or "").strip() if node is not None else ""


def _cutoff_of(number: str) -> str | None:
    digits = "".join(ch for ch in _biblio_text(number, "applicationDate") if ch.isdigit())
    return digits[:8] or None


async def _pool_for(
    number: str, queries: list[str], kipris: KiprisClient, rows: int
) -> dict[str, list[PatentSearchHit]]:
    """출원당 검색 풀. 파일 캐시 — 같은 풀로 몇 번이든 재순위한다."""
    suffix = "" if rows == 20 else f"-r{rows}"
    path = POOL_DIR / f"pool-{number}{suffix}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            query: [
                PatentSearchHit(
                    application_number=h["application_number"],
                    title=h["title"],
                    query=query,
                    metadata=h["metadata"],
                )
                for h in hits
            ]
            for query, hits in data.items()
        }
    pool: dict[str, list[PatentSearchHit]] = {}
    for query in queries:
        hits = await kipris.search(query, rows=rows)
        if hits:
            pool[query] = hits
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                query: [
                    {
                        "application_number": h.application_number,
                        "title": h.title,
                        "metadata": h.metadata,
                    }
                    for h in hits
                ]
                for query, hits in pool.items()
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return pool


def _drop_future(pool: dict, cutoff: str | None) -> dict:
    if not cutoff:
        return pool
    kept = {}
    for query, hits in pool.items():
        rows = []
        for hit in hits:
            raw = hit.metadata.get("applicationDate") or hit.metadata.get("openDate")
            digits = "".join(ch for ch in (raw or "") if ch.isdigit())[:8]
            if len(digits) == 8 and digits > cutoff:
                continue
            rows.append(hit)
        if rows:
            kept[query] = rows
    return kept


def _strip_metadata(pool: dict, keys: tuple[str, ...]) -> dict:
    """ablation 용 — 특정 신호 메타데이터를 지운 사본."""
    out = {}
    for query, hits in pool.items():
        out[query] = [
            PatentSearchHit(
                application_number=h.application_number,
                title=h.title,
                query=h.query,
                metadata={k: v for k, v in h.metadata.items() if k not in keys},
            )
            for h in hits
        ]
    return out


def variants(pool, *, families, source_tokens, exclude):
    """(이름, 순위 함수 호출) 목록 — 신호를 하나씩 켜고 끈다."""
    yield "legacy(적중수·위치)", lambda: rank_candidates(pool, cap=CAP)
    yield "rrf_v1(가중치 없음)", lambda: rank_candidates_rrf(
        _strip_metadata(pool, ("search_total", "search_field")), cap=CAP
    )
    yield "v2_full", lambda: rank_candidates_rrf(
        pool, cap=CAP, family_of=families,
        source_tokens=source_tokens, exclude=exclude,
    )
    yield "v2-특이도없이", lambda: rank_candidates_rrf(
        _strip_metadata(pool, ("search_total",)), cap=CAP,
        family_of=families, source_tokens=source_tokens, exclude=exclude,
    )
    yield "v2-계열묶기없이", lambda: rank_candidates_rrf(
        pool, cap=CAP, source_tokens=source_tokens, exclude=exclude,
    )
    yield "v2-제목유사도없이", lambda: rank_candidates_rrf(
        pool, cap=CAP, family_of=families, exclude=exclude,
    )
    yield "제목유사도만", lambda: rank_candidates_rrf(
        _strip_metadata(pool, ("search_total", "search_field")), cap=CAP,
        source_tokens=source_tokens, exclude=exclude,
    )


async def run(rows: int = 20) -> int:
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 가 필요하다 (풀 캐시 미스에만 쓴다)")
    max_rps = os.environ.get("KIPRIS_MAX_RPS", "").strip()
    kipris = KiprisClient(
        access_key=key,
        search_fields=("inventionTitle", "astrtCont"),
        rate_limiter=TokenBucket(float(max_rps)) if max_rps else None,
    )

    pairs = {
        row["application_number"]: row
        for line in (GOLDEN / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in [json.loads(line)]
    }

    # 대상: 질의 캐시가 있는 출원 (diagnose 가 만든 것)
    apps = sorted(
        path.stem.replace("queries-", "")
        for path in DIAG_DIR.glob("queries-*.json")
    )
    if not apps:
        raise SystemExit("질의 캐시가 없다 — diagnose_golden_misses.py 를 먼저 돌려라")

    # 인용 → 출원번호 해석 캐시 (diagnose 가 만든 것)
    resolved: dict[str, str] = {}
    for path in DIAG_DIR.glob("resolve-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("application_number"):
            resolved[data["citation"]] = data["application_number"]

    score = {}   # variant -> [적중, 전체]
    ranks = {}   # variant -> list of found ranks
    try:
        for number in apps:
            row = pairs.get(number)
            if row is None or not row.get("examiner_cited"):
                continue
            cited_apps = set()
            for citation in row["examiner_cited"]:
                digits = normalize_application_number(citation)
                target = resolved.get(digits, digits if len(digits) >= 12 else None)
                if target:
                    cited_apps.add(target)
            if not cited_apps:
                continue
            queries = json.loads(
                (DIAG_DIR / f"queries-{number}.json").read_text(encoding="utf-8")
            )
            pool = _drop_future(
                await _pool_for(number, queries, kipris, rows), _cutoff_of(number)
            )
            if not pool:
                continue
            # 원 질의 복원 — 확장 조합은 어떤 다른 질의의 진부분집합이다.
            originals = [
                q
                for q in queries
                if not any(
                    set(q.split()) < set(other.split())
                    for other in queries
                    if other != q
                )
            ]
            families = query_families(originals, queries)
            source_tokens = frozenset(tokenize(_biblio_text(number, "astrtCont")))
            exclude = frozenset({number})
            for name, ranker in variants(
                pool, families=families,
                source_tokens=source_tokens, exclude=exclude,
            ):
                capped = ranker()
                top = [c.application_number for c in capped]
                hit_count = len(cited_apps & set(top))
                bucket = score.setdefault(name, [0, 0])
                bucket[0] += hit_count
                bucket[1] += len(cited_apps)
                for position, appno in enumerate(top):
                    if appno in cited_apps:
                        ranks.setdefault(name, []).append(position + 1)
    finally:
        await kipris.aclose()

    print(f"출원 {len(apps)}건 · cap {CAP} — 같은 풀, 순위 변형만 교체:\n")
    width = max(len(name) for name in score)
    for name, (hits, total) in score.items():
        found = sorted(ranks.get(name, []))
        print(
            f"  {name:<{width}}  인용적중 {hits}/{total}"
            f"  (적중 순위: {found or '-'})"
        )
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=20)
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.rows)))


if __name__ == "__main__":
    main()
