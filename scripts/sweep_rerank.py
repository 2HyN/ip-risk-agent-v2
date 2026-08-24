"""재순위 변형 스위프 — 고정 풀 위에서 채점 함수만 바꿔 recall@8 을 잰다.

ablate_rank.py 가 수집해 둔 풀(labels/rank-ablation/poolv2-*-r60.json,
초록·IPC 메타데이터 포함)을 그대로 쓰므로 API 0회·초 단위다. 변형은
``VARIANTS`` 에 (이름, 채점 함수)로 등록한다 — 채점 함수는 후보 사전을 받아
{출원번호: 점수} 를 돌려주고, 높은 점수가 앞이다. 동점은 출원번호로 고정.

    PYTHONIOENCODING=utf-8 GOLDEN_DIR=... .venv/Scripts/python scripts/sweep_rerank.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

import _repo_path  # noqa: F401

from defusedxml.ElementTree import fromstring

from ip_risk_agent.intelligence.patent.ephemeral_index import tokenize
from ip_risk_agent.intelligence.patent.kipris import normalize_application_number

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(os.environ.get("GOLDEN_DIR") or (ROOT / "labels" / "golden"))
DIAG = ROOT / "labels" / "diagnosis"
POOL = ROOT / "labels" / "rank-ablation"
CAP = 8
K = 60  # RRF 상수 (운영과 동일)

_IPC_SUBCLASS = re.compile(r"([A-H]\d{2}[A-Z])")


def _biblio(number: str, tag: str) -> str:
    path = GOLDEN / "raw" / f"biblio-{number}.xml"
    if not path.exists():
        return ""
    root = fromstring(path.read_text(encoding="utf-8"))
    return next((n.text for n in root.iter(tag) if n.text), "") or ""


def _biblio_ipcs(number: str) -> set[str]:
    path = GOLDEN / "raw" / f"biblio-{number}.xml"
    if not path.exists():
        return set()
    root = fromstring(path.read_text(encoding="utf-8"))
    out = set()
    for node in root.iter("ipcNumber"):
        match = _IPC_SUBCLASS.search((node.text or "").upper().replace(" ", ""))
        if match:
            out.add(match.group(1))
    return out


def load_cases(rows: int = 60) -> list[dict]:
    """출원별 (풀 후보, 정답 인용, 원문 정보) — 컷오프·자기 제외 적용."""
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

    cases = []
    for path in sorted(POOL.glob(f"poolv2-*-r{rows}.json")):
        number = path.stem.replace("poolv2-", "").replace(f"-r{rows}", "")
        row = pairs.get(number)
        if not row or not row.get("examiner_cited"):
            continue
        cited = set()
        for citation in row["examiner_cited"]:
            digits = normalize_application_number(citation)
            target = resolved.get(digits, digits if len(digits) >= 12 else None)
            if target:
                cited.add(target)
        if not cited:
            continue
        cutoff = re.sub(r"\D", "", _biblio(number, "applicationDate"))[:8]
        queries = json.loads(
            (DIAG / f"queries-{number}.json").read_text(encoding="utf-8")
        )
        originals = [
            q for q in queries
            if not any(set(q.split()) < set(o.split()) for o in queries if o != q)
        ]

        def family_of(query: str) -> str:
            words = set(query.split())
            for original in originals:
                if words <= set(original.split()):
                    return original
            return query

        candidates: dict[str, dict] = {}
        for query, hits in json.loads(path.read_text(encoding="utf-8")).items():
            family = family_of(query)
            for position, hit in enumerate(hits):
                appno = hit["application_number"]
                if appno == number:
                    continue
                metadata = hit.get("metadata", {})
                date = re.sub(
                    r"\D", "",
                    metadata.get("applicationDate") or metadata.get("openDate") or "",
                )[:8]
                if len(date) == 8 and cutoff and date > cutoff:
                    continue
                cand = candidates.setdefault(
                    appno,
                    {
                        "title": hit["title"],
                        "abstract": hit.get("abstract", ""),
                        "families": {},
                        "best_position": position,
                        "ipc": metadata.get("ipc", ""),
                        "queries": set(),
                        "hits": [],
                    },
                )
                if not cand["abstract"] and hit.get("abstract"):
                    cand["abstract"] = hit["abstract"]
                cand["queries"].add(query)
                cand["hits"].append(
                    {
                        "field": metadata.get("search_field", ""),
                        "total": (
                            int(metadata["search_total"])
                            if str(metadata.get("search_total", "")).isdigit()
                            else None
                        ),
                        "position": position,
                    }
                )
                cand["best_position"] = min(cand["best_position"], position)
                weight = 1.0
                total = metadata.get("search_total", "")
                if str(total).isdigit():
                    weight /= 1.0 + math.log10(1.0 + float(total))
                if metadata.get("search_field") == "astrtCont":
                    weight *= 0.7
                contribution = weight / (K + position + 1)
                cand["families"][family] = max(
                    cand["families"].get(family, 0.0), contribution
                )
        if not candidates:
            continue
        cases.append(
            {
                "number": number,
                "cited": cited,
                "candidates": candidates,
                "source_abstract": _biblio(number, "astrtCont"),
                "source_ipcs": _biblio_ipcs(number),
                "queries": queries,
            }
        )
    return cases


# ------------------------------------------------------------ 채점 부품


def bm25_scores(
    case: dict,
    *,
    k1: float = 1.2,
    b: float = 0.75,
    title_weight: int = 1,
    query_tokens: frozenset[str] | None = None,
    query_token_boost: float = 0.0,
    idf_ceiling_df_share: float = 1.0,
    tokenizer=tokenize,
) -> dict[str, float]:
    src = set(tokenizer(case["source_abstract"]))
    docs = {
        appno: Counter(
            list(tokenizer(cand["title"])) * title_weight
            + list(tokenizer(cand["abstract"]))
        )
        for appno, cand in case["candidates"].items()
    }
    df: Counter[str] = Counter()
    for freq in docs.values():
        for token in freq:
            df[token] += 1
    corpus = len(docs)
    avgdl = sum(sum(freq.values()) for freq in docs.values()) / corpus

    def score(appno: str) -> float:
        freq = docs[appno]
        length = sum(freq.values()) or 1
        out = 0.0
        for token in src:
            occurrences = freq.get(token)
            if not occurrences:
                continue
            if df[token] / corpus > idf_ceiling_df_share:
                continue  # 풀에 만연한 토큰(특허 상투어)은 신호가 아니다
            idf = math.log(1.0 + (corpus - df[token] + 0.5) / (df[token] + 0.5))
            boost = (
                1.0 + query_token_boost
                if query_tokens and token in query_tokens
                else 1.0
            )
            out += (
                boost * idf * occurrences * (k1 + 1.0)
                / (occurrences + k1 * (1.0 - b + b * length / avgdl))
            )
        return out

    return {appno: score(appno) for appno in docs}


def rrf_scores(case: dict) -> dict[str, float]:
    return {
        appno: sum(cand["families"].values())
        for appno, cand in case["candidates"].items()
    }


def fuse_multiply(bm25: dict, rrf: dict) -> dict[str, float]:
    rrf_max = max(rrf.values()) or 1.0
    if max(bm25.values() or [0.0]) == 0.0:
        return dict(rrf)
    return {appno: bm25[appno] * (1.0 + rrf[appno] / rrf_max) for appno in bm25}


def ipc_multiplier(case: dict, scores: dict, gain: float) -> dict[str, float]:
    out = {}
    for appno, value in scores.items():
        match = _IPC_SUBCLASS.search(
            (case["candidates"][appno]["ipc"] or "").upper().replace(" ", "")
        )
        hit = match and match.group(1) in case["source_ipcs"]
        out[appno] = value * (1.0 + gain) if hit else value
    return out


def word_only(text: str) -> list[str]:
    return [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text)]


def char_trigram(text: str) -> list[str]:
    out = []
    for word in re.findall(r"[가-힣A-Za-z0-9]+", text):
        if len(word) <= 3:
            out.append(word)
        else:
            out.extend(word[i : i + 3] for i in range(len(word) - 2))
    return out


# ------------------------------------------------------------ 상투어·정밀 판정

#: 한국어 특허 상투어 — 원문(질의) 쪽에서만 제거한다. 실패 사례 실측: 놓친
#: 인용의 BM25 질량 55% 가 이런 토큰에서 나왔고, 무관 문서가 "상기·하는·를"
#: 반복만으로 top-5 에 올랐다. 풀-상대 DF 가지치기는 주제어까지 자르므로
#: (실측 9/83→2/83 악화) 절대 목록이어야 한다.
_PATENT_STOPWORDS = {
    "발명", "방법", "장치", "시스템", "제공", "포함", "특징", "상기", "관한",
    "위한", "단계", "구성", "수단", "구비", "형성", "이루어진", "이용", "사용",
    "하는", "되는", "있는", "한다", "위해", "따라", "통해", "따른", "대한",
    "제1", "제2", "및", "또는",
}
_STOP_TOKENS = frozenset(
    token
    for word in _PATENT_STOPWORDS
    for token in ([word] + [word[i : i + 2] for i in range(len(word) - 1)])
)


def stripped_query_counter(text: str) -> Counter:
    """질의측 토큰 Counter — 상투어(와 그 bigram 파편) 제거, TF 보존."""
    return Counter(t for t in tokenize(text) if t not in _STOP_TOKENS)


def bm25_qtf_scores(case: dict, *, k3: float = 8.0, **kw) -> dict[str, float]:
    """질의 TF 포화 + 상투어 제거 BM25. 문서 쪽은 건드리지 않는다."""
    qtf = stripped_query_counter(case["source_abstract"])
    tokenizer = kw.pop("tokenizer", tokenize)
    docs = {
        appno: Counter(tokenizer(f"{cand['title']} {cand['abstract']}"))
        for appno, cand in case["candidates"].items()
    }
    df: Counter[str] = Counter()
    for freq in docs.values():
        for token in freq:
            df[token] += 1
    corpus = len(docs)
    avgdl = sum(sum(freq.values()) for freq in docs.values()) / corpus
    k1, b = kw.pop("k1", 1.2), kw.pop("b", 0.75)

    def score(appno: str) -> float:
        freq = docs[appno]
        length = sum(freq.values()) or 1
        out = 0.0
        for token, count in qtf.items():
            occurrences = freq.get(token)
            if not occurrences:
                continue
            idf = math.log(1.0 + (corpus - df[token] + 0.5) / (df[token] + 0.5))
            weight = count * (k3 + 1.0) / (k3 + count)
            out += (
                weight * idf * occurrences * (k1 + 1.0)
                / (occurrences + k1 * (1.0 - b + b * length / avgdl))
            )
        return out

    return {appno: score(appno) for appno in docs}


def _title_precise(cand: dict, total_cap: int) -> bool:
    return any(
        h["field"] == "inventionTitle"
        and h["total"] is not None
        and h["total"] <= total_cap
        for h in cand["hits"]
    )


def reserved_slots(case: dict, scores: dict, *, slots: int = 2, total_cap: int = 10):
    """상위 6 + 정밀 제목 적중 예약 2석. 예약이 모자라면 7·8위로 채운다."""
    ordered = sorted(scores, key=lambda a: (-scores[a], a))
    head = ordered[: CAP - slots]
    reserve_pool = [
        appno
        for appno in ordered[CAP - slots :]
        if _title_precise(case["candidates"][appno], total_cap)
    ]
    chosen = head + reserve_pool[:slots]
    for appno in ordered[CAP - slots :]:
        if len(chosen) >= CAP:
            break
        if appno not in chosen:
            chosen.append(appno)
    return chosen


def precise_tail(case: dict, scores: dict, *, tail_to: int = 24, total_cap: int = 30):
    """판정 대상 확장: top-8 + 9~24위 중 정밀 제목 적중. (개수도 돌려준다)"""
    ordered = sorted(scores, key=lambda a: (-scores[a], a))
    selection = list(ordered[:CAP])
    for appno in ordered[CAP:tail_to]:
        if _title_precise(case["candidates"][appno], total_cap):
            selection.append(appno)
    return selection


# ------------------------------------------------------------ 변형 정의


def _top(scores: dict) -> list[str]:
    return sorted(scores, key=lambda a: (-scores[a], a))[:CAP]


def variants(case: dict):
    """(이름, 최종 판정 대상 목록) — 목록 크기가 곧 문서당 대조 비용이다."""
    rrf = rrf_scores(case)
    current = fuse_multiply(bm25_scores(case), rrf)
    qtf = fuse_multiply(bm25_qtf_scores(case), rrf)
    yield "현행 bm25×(1+rrf)", _top(current)
    yield "질의TF+상투어컷", _top(qtf)
    yield "예약슬롯2 (현행 위)", reserved_slots(case, current)
    yield "예약슬롯2 (질의TF 위)", reserved_slots(case, qtf)
    yield "정밀꼬리 확장 (현행 위)", precise_tail(case, current)
    yield "정밀꼬리 확장 (질의TF 위)", precise_tail(case, qtf)
    yield "정밀꼬리 (질의TF, total≤60)", precise_tail(
        case, qtf, total_cap=60
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=60, help="풀 깊이 (캐시 접미사)")
    args = parser.parse_args()
    global POOL_GLOB
    cases = load_cases(rows=args.rows)
    total = sum(len(case["cited"]) for case in cases)
    ceiling = sum(
        len(case["cited"] & set(case["candidates"])) for case in cases
    )
    tally: dict[str, list] = {}
    for case in cases:
        for name, selection in variants(case):
            found = [
                position + 1
                for position, appno in enumerate(selection)
                if appno in case["cited"]
            ]
            bucket = tally.setdefault(name, [0, [], 0])
            bucket[0] += len(found)
            bucket[1].extend(found)
            bucket[2] += len(selection)
    print(
        f"출원 {len(cases)}건 · 인용 {total}건 · 풀 천장 {ceiling}"
        f" · rows {args.rows} · 기본 cap {CAP}\n"
    )
    width = max(len(name) for name in tally)
    for name, (hits, ranks_found, size) in sorted(
        tally.items(), key=lambda item: -item[1][0]
    ):
        print(
            f"  {name:<{width}}  {hits}/{total}"
            f"  판정대상 평균 {size / len(cases):.1f}건  순위 {sorted(ranks_found)}"
        )


if __name__ == "__main__":
    main()
