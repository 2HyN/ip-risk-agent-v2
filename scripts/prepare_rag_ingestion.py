"""Validate and summarize the approved RAG corpus without external writes."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from ip_risk_agent.intelligence.rag.ingestion import InMemoryCorpusUploader, ingest

ROOT = Path(__file__).resolve().parents[1]


async def prepare(manifest: Path) -> dict[str, object]:
    uploader = InMemoryCorpusUploader()
    report = await ingest(manifest, uploader, strict=True)
    return {
        "corpus_version": report.corpus_version,
        "document_count": len(report.prepared),
        "uploaded": report.uploaded,
        "source_ids": [document.source_id for document in report.prepared],
        "checksums_verified": True,
        "external_write_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "rag-corpus" / "manifest.yaml",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(prepare(args.manifest.resolve())), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
