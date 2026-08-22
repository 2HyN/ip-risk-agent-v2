"""승인된 corpus 를 RAG Engine 에 실제로 올린다.

``prepare_rag_ingestion.py`` 는 올리지 않는다 — 매니페스트를 읽고 지문을 대조해 보여
주기만 한다. 이 스크립트가 실제로 쓰는 쪽이다.

## 실수로 운영 corpus 를 건드리지 않게

외부에 쓰는 일이라 되돌릴 수 없다. 그래서 세 가지를 요구한다.

* ``--corpus-id`` 를 **직접 적어야 한다.** 환경변수에서 읽지 않는다 — 배포된
  ``RAG_CORPUS_ID`` 를 기본값으로 두면 손이 미끄러지는 순간 운영이 바뀐다.
* ``--confirm`` 없이는 무엇을 할지 보여 주기만 하고 끝난다.
* 코드가 그 corpus 를 다룰 준비가 됐는지 확인하는 것은 사람의 몫이다. 특히 관련성
  게이트(0-G)가 **배포된 리비전에 들어 있는지** 보고 나서 올린다. 게이트가 없는 채로
  큰 corpus 를 올리면 틀린 근거가 붙는 양이 그만큼 늘어난다.

## 왜 새 corpus 를 권하는가

corpus 판본과 코드는 함께 움직여야 한다. 새 corpus 에 올리고, 새 리비전이
``RAG_CORPUS_ID`` 와 ``RAG_CORPUS_VERSION`` 을 함께 바꿔 가리키면 전환이 한 번에
일어난다. 운영 corpus 에 덧쓰면 **아직 옛 코드가 도는 동안** 내용이 바뀐다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "shared" / "contracts" / "python"))

from ip_risk_agent.intelligence.rag.corpus_manifest import load_manifest  # noqa: E402
from ip_risk_agent.intelligence.rag.ingestion import (  # noqa: E402
    InMemoryCorpusUploader,
    ingest,
)
from ip_risk_agent.intelligence.rag.vertex_upload import (  # noqa: E402
    VertexRagCorpusUploader,
)

SCOPE = "https://www.googleapis.com/auth/cloud-platform"


async def run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    approved = manifest.validate_for_ingestion()

    print(f"매니페스트   {manifest_path}")
    print(f"corpus 판본  {manifest.corpus_version}")
    print(f"승인된 문서  {len(approved)} 편")
    print(f"대상 corpus  {args.corpus_id}  ({args.region})")

    if not (args.confirm or args.verify):
        print()
        print("--confirm 도 --verify 도 없어 아무것도 하지 않았다.")
        print("올리기 전에 확인할 것:")
        print("  * 관련성 게이트(0-G)가 **배포된 리비전**에 들어 있는가")
        print("  * 이 corpus 가 운영이 쓰는 것인가, 새로 만든 것인가")
        print("  * 올린 뒤 RAG_CORPUS_VERSION 을 매니페스트 값과 맞출 사람이 있는가")
        return 0

    import google.auth

    credentials, project = google.auth.default(scopes=[SCOPE])
    project_id = args.project_id or project
    if not project_id:
        print("project 를 찾지 못했다. --project-id 로 지정하라.", file=sys.stderr)
        return 2

    uploader = VertexRagCorpusUploader(
        project_id=project_id,
        region=args.region,
        corpus_id=args.corpus_id,
        credentials=credentials,
    )

    if args.confirm:
        report = await ingest(manifest_path, uploader, strict=True)
        prepared = report.prepared
        print()
        print(f"올렸다 — {report.uploaded} 편")
    else:
        # 올리지 않고 확인만 한다. 준비 단계는 그대로 거쳐야 지문을 계산한다.
        report = await ingest(manifest_path, InMemoryCorpusUploader(), strict=True)
        prepared = report.prepared

    audit = await uploader.audit(prepared, report.corpus_version)
    print()
    print(json.dumps(audit, ensure_ascii=False, indent=2))

    if audit["clean"]:
        print()
        print("corpus 가 매니페스트와 정확히 같다.")
        if args.confirm:
            print(
                "다음 — 배포에서 RAG_CORPUS_ID 와 RAG_CORPUS_VERSION 을 "
                f"'{args.corpus_id}' / '{report.corpus_version}' 으로 함께 맞춘다."
            )
        return 0

    print()
    print("**corpus 가 매니페스트와 다르다.** 위 목록을 보고 처리한다.", file=sys.stderr)
    if audit["unexpected"] and args.prune:
        removed = await uploader.prune(list(audit["unexpected"]))
        print(f"매니페스트 밖 문서 {removed} 편을 지웠다. 다시 --verify 하라.")
    elif audit["unexpected"]:
        print("매니페스트 밖 문서는 --prune 으로 지운다.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default=str(ROOT / "rag-corpus" / "manifest.yaml")
    )
    parser.add_argument(
        "--corpus-id",
        required=True,
        help="올릴 corpus 의 숫자 id. 환경변수에서 읽지 않는다 — 직접 적어야 한다",
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--project-id", default=None)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="실제로 올린다. 올린 뒤 곧바로 확인까지 한다",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="올리지 않고, 이미 올라간 것이 매니페스트와 같은지만 확인한다",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="매니페스트 밖 문서를 지운다. --verify 나 --confirm 과 함께 쓴다",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
