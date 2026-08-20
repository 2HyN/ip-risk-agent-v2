from __future__ import annotations

import asyncio
from pathlib import Path

from scripts.prepare_rag_ingestion import prepare
from scripts.validate_gcp_deployment import validate


ROOT = Path(__file__).resolve().parents[2]


def test_repository_owned_gcp_inputs_are_self_consistent() -> None:
    assert validate(ROOT) == []


def test_rag_ingestion_dry_run_is_manifest_bounded_and_write_free() -> None:
    report = asyncio.run(prepare(ROOT / "rag-corpus" / "manifest.yaml"))
    assert report == {
        "corpus_version": "2026-08-14.1",
        "document_count": 3,
        "uploaded": 3,
        "source_ids": [
            "agpl-3.0-obligations",
            "lgpl-2.1-obligations",
            "permissive-notice",
        ],
        "checksums_verified": True,
        "external_write_performed": False,
    }
