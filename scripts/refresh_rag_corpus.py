"""SPDX 가 바뀌었는지 보고, 바뀌었으면 다시 만들어 올리고 확인까지 한다.

## 왜 한 명령인가

corpus 를 갱신하는 일은 네 단계였고 **사이가 끊기면 조용히 어긋난다.**

1. SPDX 를 받아 다시 만든다 (`build_rag_corpus.py`)
2. 판본을 올린다
3. RAG Engine 에 올린다 (`ingest_rag_corpus.py`)
4. 배포 환경변수 ``RAG_CORPUS_VERSION`` 을 매니페스트와 맞춘다

실제로 3 을 빠뜨린 채로 오래 있었고(전문이 하나도 안 올라가 있었다), 4 는 지금도
어긋나 있다 — 배포는 ``2026-08-21.1``, 매니페스트는 그보다 뒤다. 검증기가 환경변수의
**이름**만 보고 값은 못 보기 때문에 코드가 잡아 주지 못한다.

그래서 하나로 묶는다. 사람이 기억해야 할 것을 줄이는 것이 이 스크립트의 전부다.

## 언제 돌리는가

* **주기적으로** — SPDX 는 몇 달에 한 번 목록을 고친다. 자주 돌려도 바뀐 것이 없으면
  아무 일도 하지 않는다.
* **소식을 들었을 때** — 어떤 패키지가 라이선스를 바꿨다는 이야기가 돌면 그때.

``--check`` 는 **아무것도 쓰지 않는다.** 바뀐 것이 있는지만 종료 코드로 답하므로
예약 작업이나 CI 에서 안전하게 돌릴 수 있다 (바뀌었으면 1, 아니면 0).

## 판본과 배포는 함께 움직인다

corpus 판본은 판정마다 ``rag_corpus_version`` 으로 기록된다. 그 값이 있어야 "판정이 왜
달라졌는가" 에서 **우리 지식이 달라졌다** 를 가려낼 수 있다 (`DEVELOPMENT_SPEC.md`
§7.4). 그래서 올린 뒤에는 배포가 그 판본을 가리켜야 하고, 이 스크립트는 마지막에 그
값을 찍어 준다.

사용법::

    python scripts/refresh_rag_corpus.py --check
    python scripts/refresh_rag_corpus.py --corpus-id <id> --region <region> --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

ROOT = Path(__file__).resolve().parents[1]
# 이웃 스크립트(`build_rag_corpus` · `ingest_rag_corpus`)를 들이기 위해서다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_rag_corpus import build  # noqa: E402
from ingest_rag_corpus import _probe  # noqa: E402

from ip_risk_agent.intelligence.rag.corpus_manifest import load_manifest  # noqa: E402
from ip_risk_agent.intelligence.rag.ingestion import (  # noqa: E402
    InMemoryCorpusUploader,
    ingest,
)
from ip_risk_agent.intelligence.rag.vertex_upload import (  # noqa: E402
    VertexRagCorpusUploader,
)

MANIFEST = ROOT / "rag-corpus" / "manifest.yaml"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"


async def run(args: argparse.Namespace) -> int:
    before = load_manifest(MANIFEST).corpus_version
    print("== 1. SPDX 를 보고 다시 만들면 달라지는지 확인한다")
    changed = build(check=True, version=None) == 1
    print()

    if not changed and not args.force:
        print(f"바뀐 것이 없다. corpus 판본 {before} 그대로다.")
        print("배포가 그 판본을 가리키는지만 확인하면 된다.")
        return 0

    if args.check:
        print("**다시 만들면 달라진다.** --confirm 으로 갱신한다.")
        return 1

    if not args.confirm:
        print("**다시 만들면 달라진다.** --confirm 이 없어 여기서 멈춘다.")
        return 1

    if not (args.corpus_id and args.region):
        print(
            "--confirm 에는 --corpus-id 와 --region 이 함께 필요하다.",
            file=sys.stderr,
        )
        return 2

    print("== 2. 다시 만든다")
    if build(check=False, version=args.corpus_version) != 0:
        return 1
    manifest = load_manifest(MANIFEST)
    print()

    print(f"== 3. RAG Engine 에 올린다 — corpus {args.corpus_id} ({args.region})")
    import google.auth

    credentials, project = google.auth.default(scopes=[SCOPE])
    project_id = args.project_id or project
    uploader = VertexRagCorpusUploader(
        project_id=project_id,
        region=args.region,
        corpus_id=args.corpus_id,
        credentials=credentials,
    )
    report = await ingest(MANIFEST, InMemoryCorpusUploader(), strict=True)
    uploaded = await uploader.upload(report.prepared, manifest.corpus_version)
    print(f"올렸다 — {uploaded} 편")
    print()

    print("== 4. 올라간 것이 매니페스트와 같은지 본다")
    audit = await uploader.audit(report.prepared, manifest.corpus_version)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if not audit["clean"]:
        print()
        print("**corpus 가 매니페스트와 다르다.**", file=sys.stderr)
        if audit["unexpected"]:
            print(
                "옛 판본의 문서가 남아 있다. ingest_rag_corpus.py --prune 으로 지운다.",
                file=sys.stderr,
            )
        return 1
    print()

    print("== 5. 실제로 검색해 본다")
    probe = await _probe(
        project_id=project_id,
        region=args.region,
        corpus_id=args.corpus_id,
        corpus_version=manifest.corpus_version,
        documents=report.prepared,
        count=args.probe_count,
    )
    print(json.dumps(probe, ensure_ascii=False, indent=2))
    if not probe["passed"]:
        print()
        print("**검색이 문서를 되찾지 못한다.**", file=sys.stderr)
        return 1

    print()
    print("끝났다.")
    print(f"  corpus 판본  {before} → {manifest.corpus_version}")
    print("  다음 배포에서 아래를 함께 맞춘다:")
    print(f"    RAG_CORPUS_ID       {args.corpus_id}")
    print(f"    RAG_CORPUS_VERSION  {manifest.corpus_version}")
    print()
    print("  그리고 rag-corpus/ 와 corpus_coverage.json 을 커밋한다 —")
    print("  코드가 읽는 커버리지 색인이 함께 바뀌었다.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="아무것도 쓰지 않고, 바뀐 것이 있으면 1 로 끝난다",
    )
    parser.add_argument(
        "--confirm", action="store_true", help="다시 만들고 올리고 확인까지 한다"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="바뀐 것이 없어도 다시 올린다 (corpus 가 비었을 때 쓴다)",
    )
    parser.add_argument("--corpus-id")
    parser.add_argument("--region")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--corpus-version", default=None)
    parser.add_argument("--probe-count", type=int, default=5)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
