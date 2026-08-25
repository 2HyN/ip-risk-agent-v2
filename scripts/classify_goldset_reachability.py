"""골든셋 인용 전수의 키워드 도달성 분류 — 한계 규정과 처방 분리의 근거.

개발 조건(비벌크·API 검색만)과 KIPRIS 특성(키워드 AND 검색)을 전제로,
심사관 인용 86건을 세 급으로 나눈다:

  A1 현행 질의 도달 — 지금 추출 질의(확장 포함)가 인용의 제목/초록에
     AND-매치한다 (부분문자열 근사). 검색이 데려올 수 있는 급 — 실패는
     깊이·순위·판정 폭의 문제다.
  A2 어휘 도출 가능 — 현행 질의는 안 맞지만 원문 초록과 인용 텍스트의
     공유 실질 어휘가 2개 이상 — 질의 생성이 좋아지면 도달 가능한 급.
  B  어휘 불일치 — 공유 실질 어휘 < 2. 키워드 AND 검색으로는 원리상
     불가 — 유사 키워드(동의어·상위어) 확장이나 다른 채널이 필요한 급.

급마다 실제 깔때기(풀 진입 → v3 판정 도달)를 겹쳐 어디서 죽는지 보인다.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GOLDEN_DIR=... \
      .venv/Scripts/python scripts/classify_goldset_reachability.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import _repo_path  # noqa: F401

from defusedxml.ElementTree import fromstring

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
DIAG = ROOT / "labels" / "diagnosis"
POOL = ROOT / "labels" / "rank-ablation"

_STOPWORDS = {
    "있는", "있다", "하는", "하고", "하여", "위한", "위해", "따라", "따른",
    "대한", "대해", "및", "또는", "또한", "그리고", "본", "상기", "발명",
    "제공", "포함", "이용", "사용", "관한", "관련", "통해", "통한", "수",
    "것", "때", "등", "중", "장치", "방법", "시스템", "단계", "구성",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[가-힣A-Za-z]{2,}", text) if w not in _STOPWORDS
    }


def _contains_all(words: list[str], text: str) -> bool:
    return all(word in text for word in words)


def _biblio_fields(path: Path) -> dict:
    root = fromstring(path.read_text(encoding="utf-8"))
    title = ""
    summary = next(root.iter("biblioSummaryInfo"), None)
    if summary is not None:
        title = (summary.findtext("inventionTitle") or "").strip()
    abstract = ""
    for node in root.iter("astrtCont"):
        abstract = (node.text or "").strip()
        if abstract:
            break
    return {"title": title, "abstract": abstract}


def _fetch_biblio(number: str, key: str) -> dict | None:
    import httpx
    from ip_risk_agent.intelligence.patent.kipris import BASE_URL, DETAIL_PATH

    path = DIAG / f"biblio-{number}.xml"
    if not path.exists():
        response = httpx.get(
            f"{BASE_URL}/{DETAIL_PATH}",
            params={"applicationNumber": number, "ServiceKey": key},
            timeout=20.0,
        )
        response.raise_for_status()
        DIAG.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
    return _biblio_fields(path)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    from ip_risk_agent.intelligence.patent.kipris import normalize_application_number

    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요 (미캐시 인용 공보 조회)")

    sys.path.insert(0, str(ROOT / "scripts"))
    from sweep_rerank import (
        bm25_scores,
        fuse_multiply,
        load_cases,
        precise_tail,
        rrf_scores,
    )

    pairs = {
        json.loads(line)["application_number"]: json.loads(line)
        for line in (GOLDEN / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    resolved = {}
    for path in DIAG.glob("resolve-*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("application_number"):
            resolved[data["citation"]] = data["application_number"]

    cases = {case["number"]: case for case in load_cases()}

    rows = []
    for number, case in sorted(cases.items()):
        row = pairs[number]
        queries = json.loads(
            (DIAG / f"queries-{number}.json").read_text(encoding="utf-8")
        )
        source_vocab = _tokens(case["source_abstract"])
        scores = fuse_multiply(bm25_scores(case), rrf_scores(case))
        selection = set(precise_tail(case, scores))
        pool_apps = set(case["candidates"])

        for citation in row.get("examiner_cited") or []:
            digits = normalize_application_number(citation)
            target = resolved.get(digits, digits if len(digits) >= 12 else None)
            if not target:
                rows.append({"class": "UNRESOLVED", "app": number, "cite": digits})
                continue
            cited = _fetch_biblio(target, key)
            cited_text = f"{cited['title']} {cited['abstract']}"
            query_hit = any(
                _contains_all(q.split(), cited["title"])
                or _contains_all(q.split(), cited["abstract"])
                for q in queries
            )
            shared = source_vocab & _tokens(cited_text)
            klass = "A1" if query_hit else ("A2" if len(shared) >= 2 else "B")
            rows.append(
                {
                    "class": klass,
                    "app": number,
                    "cite": digits,
                    "cited_app": target,
                    "cited_title": cited["title"][:40],
                    "shared": len(shared),
                    "in_pool": target in pool_apps,
                    "in_judgment": target in selection,
                }
            )

    DIAG.mkdir(parents=True, exist_ok=True)
    (DIAG / "reachability.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    funnel: dict[str, list[int]] = {}
    for record in rows:
        bucket = funnel.setdefault(record["class"], [0, 0, 0])
        bucket[0] += 1
        if record.get("in_pool"):
            bucket[1] += 1
        if record.get("in_judgment"):
            bucket[2] += 1
    total = len(rows)
    print(f"인용 {total}건의 도달성 분류 (급 → 전체 / 풀 진입 / v3 판정 도달):\n")
    for klass in ("A1", "A2", "B", "UNRESOLVED"):
        if klass in funnel:
            n, in_pool, judged = funnel[klass]
            print(f"  {klass}: {n:3d}건  →  풀 {in_pool}건  →  판정 {judged}건")
    print(f"\n세부 → {DIAG / 'reachability.json'}")


if __name__ == "__main__":
    main()
