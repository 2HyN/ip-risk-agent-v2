"""의미 임베딩 재순위 측정 — 어휘(BM25) 한계의 질적 대안을 잰다.

## 왜

어휘 계열(BM25·TF-IDF 코사인·파라미터 그리드 ~40변형)은 전부 10/83 에서
멈췄고, 심층 miss 는 원문과 표면 어휘가 거의 안 겹친다(동의어·이형태).
질적으로 다른 신호는 의미 임베딩뿐이다 — 검색 히트에 이미 실려 오는
제목·초록을 벡터화해 원문과 코사인 유사도로 재순위한다.

## 어떻게

1. ``--fetch``: 고정 풀(poolv2-*-r60)의 유니크 후보와 원문 초록을
   gemini-embedding-001(Vertex ADC)로 임베딩해 캐시한다. 문서는
   RETRIEVAL_DOCUMENT, 원문은 RETRIEVAL_QUERY 태스크 타입.
2. ``--measure``: 캐시만으로 변형별 recall@8 을 잰다 (API 0회) —
   임베딩 단독 / ×검색합의 / BM25 와 순위 융합 / 점수 혼합.

    PYTHONIOENCODING=utf-8 GCP_PROJECT_ID=... GOLDEN_DIR=... \
      .venv/Scripts/python scripts/embed_rerank.py --fetch
    ... --measure
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import _repo_path  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
EMB_DIR = ROOT / "labels" / "embeddings"
MODEL = "gemini-embedding-001"
DIM = 768
BATCH = 25
_TEXT_LIMIT = 1500  # 임베딩 입력 절단 — 제목+초록이면 충분


def _client():
    from google import genai

    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project:
        raise SystemExit("GCP_PROJECT_ID(Vertex ADC) 가 필요하다")
    return genai.Client(
        vertexai=True,
        project=project,
        location=os.environ.get("VERTEX_LOCATION", "global"),
    )


def _load_vectors(name: str) -> dict[str, list[float]]:
    path = EMB_DIR / f"{name}.jsonl"
    vectors = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                vectors[record["id"]] = record["v"]
    return vectors


def _append_vectors(name: str, records: list[tuple[str, list[float]]]) -> None:
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    with (EMB_DIR / f"{name}.jsonl").open("a", encoding="utf-8") as handle:
        for identifier, vector in records:
            handle.write(
                json.dumps(
                    {"id": identifier, "v": [round(x, 5) for x in vector]},
                )
                + "\n"
            )


def _embed_batch(client, texts: list[str], task: str) -> list[list[float]]:
    from google.genai import types

    response = client.models.embed_content(
        model=MODEL,
        contents=[t[:_TEXT_LIMIT] for t in texts],
        config=types.EmbedContentConfig(
            task_type=task, output_dimensionality=DIM
        ),
    )
    return [e.values for e in response.embeddings]


def fetch() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from sweep_rerank import load_cases

    cases = load_cases()
    client = _client()

    documents = _load_vectors("documents")
    queries = _load_vectors("queries")

    todo_docs: dict[str, str] = {}
    todo_queries: dict[str, str] = {}
    for case in cases:
        if case["number"] not in queries:
            todo_queries[case["number"]] = case["source_abstract"]
        for appno, cand in case["candidates"].items():
            if appno not in documents and appno not in todo_docs:
                todo_docs[appno] = f"{cand['title']}\n{cand['abstract']}"
    print(f"임베딩 대상: 문서 {len(todo_docs)}건 · 원문 {len(todo_queries)}건")

    for name, todo, task in (
        ("queries", todo_queries, "RETRIEVAL_QUERY"),
        ("documents", todo_docs, "RETRIEVAL_DOCUMENT"),
    ):
        items = list(todo.items())
        for start in range(0, len(items), BATCH):
            chunk = items[start : start + BATCH]
            vectors = _embed_batch(client, [t for _, t in chunk], task)
            _append_vectors(name, list(zip([i for i, _ in chunk], vectors)))
            if start % (BATCH * 20) == 0:
                print(f"  {name}: {start + len(chunk)}/{len(items)}")
    print("임베딩 완료")
    return 0


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def measure() -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from sweep_rerank import (
        CAP,
        bm25_scores,
        fuse_multiply,
        load_cases,
        precise_tail,
        rrf_scores,
    )

    documents = _load_vectors("documents")
    queries = _load_vectors("queries")
    cases = load_cases()
    total = sum(len(c["cited"]) for c in cases)

    def top(scores):
        return sorted(scores, key=lambda a: (-scores[a], a))[:CAP]

    def rank_of(scores):
        ordered = sorted(scores, key=lambda a: (-scores[a], a))
        return {appno: index for index, appno in enumerate(ordered)}

    K = 60
    tally: dict[str, list] = {}
    missing = 0
    for case in cases:
        source_vec = queries.get(case["number"])
        if source_vec is None:
            continue
        emb = {}
        for appno in case["candidates"]:
            vec = documents.get(appno)
            if vec is None:
                missing += 1
                emb[appno] = 0.0
            else:
                emb[appno] = _cosine(source_vec, vec)
        rrf = rrf_scores(case)
        bm25 = fuse_multiply(bm25_scores(case), rrf)
        emb_rrf = fuse_multiply(emb, rrf)
        lex_rank, emb_rank = rank_of(bm25), rank_of(emb)
        fused_rank = {
            appno: 1.0 / (K + lex_rank[appno] + 1) + 1.0 / (K + emb_rank[appno] + 1)
            for appno in emb
        }
        bm_max = max(bm25.values()) or 1.0
        em_max = max(emb.values()) or 1.0
        blend = {
            appno: 0.5 * bm25[appno] / bm_max + 0.5 * emb[appno] / em_max
            for appno in emb
        }
        selections = {
            "현행 BM25×(1+rrf)": top(bm25),
            "임베딩 단독": top(emb),
            "임베딩×(1+rrf)": top(emb_rrf),
            "순위융합(BM25,임베딩)": top(fused_rank),
            "점수혼합 0.5/0.5": top(blend),
            "정밀꼬리(현행 위) = v3": precise_tail(case, bm25),
            "정밀꼬리(점수혼합 위)": precise_tail(case, blend),
        }
        for name, selection in selections.items():
            bucket = tally.setdefault(name, [0, 0, 0])
            bucket[0] += len(case["cited"] & set(selection))
            bucket[1] += len(selection)
            bucket[2] += 1 if case["cited"] & set(selection) else 0
    print(f"인용 {total}건 · 출원 {len(cases)}건 · 임베딩 결측 {missing}건\n")
    width = max(len(n) for n in tally)
    for name, (hits, size, apps) in sorted(tally.items(), key=lambda kv: -kv[1][0]):
        print(
            f"  {name:<{width}}  문헌 {hits}/{total} · 건단위 {apps}/{len(cases)}"
            f" · 판정대상 평균 {size / len(cases):.1f}"
        )
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--measure", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        sys.exit(fetch())
    if args.measure:
        sys.exit(measure())
    parser.error("--fetch 또는 --measure")


if __name__ == "__main__":
    main()
