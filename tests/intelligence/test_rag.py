"""RAG 회귀 테스트 (Agent 3 Spec 46).

실제 클라우드 서비스를 요구하지 않는다. 매니페스트 검증과 검색 규약만 확인한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ip_risk_agent.intelligence.common.errors import ProviderFailureError
from ip_risk_agent.intelligence.license.explanation import ReferenceChunk
from ip_risk_agent.intelligence.rag.corpus_manifest import (
    CorpusManifest,
    ManifestError,
    load_manifest,
)
from ip_risk_agent.intelligence.rag.ingestion import (
    InMemoryCorpusUploader,
    checksum,
    ingest,
)
from ip_risk_agent.intelligence.rag.retrieval import InMemoryReferenceRetriever
from ip_risk_agent.intelligence.rag.versioning import (
    CorpusVersion,
    InvalidCorpusVersion,
)

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "rag-corpus"

CHUNKS = [
    ReferenceChunk(
        "agpl-3.0-obligations",
        "agpl:network",
        "네트워크를 통해 서비스를 제공하는 경우에도 소스코드를 제공해야 한다.",
        "https://spdx.org/licenses/AGPL-3.0-only.html",
        {"family": "gpl"},
    ),
    ReferenceChunk(
        "permissive-notice",
        "mit:notice",
        "배포물에 라이선스 사본과 저작권 고지를 포함한다.",
        "https://spdx.org/licenses/MIT.html",
        {"family": "permissive"},
    ),
]


# --------------------------------------------------------------- 버전


def test_corpus_version_parses_and_compares():
    assert str(CorpusVersion.parse("2026-08-14.1")) == "2026-08-14.1"
    assert CorpusVersion.parse("2026-08-14.1") < CorpusVersion.parse("2026-08-14.2")
    assert str(CorpusVersion.parse("2026-08-14.1").bump()) == "2026-08-14.2"


def test_invalid_corpus_version_is_rejected():
    with pytest.raises(InvalidCorpusVersion):
        CorpusVersion.parse("v1")


# --------------------------------------------------------------- 검색


def test_retrieval_returns_top_k_by_relevance():
    retriever = InMemoryReferenceRetriever(CHUNKS, "2026-08-14.1")
    found = asyncio.run(retriever.retrieve("네트워크 소스코드 제공", top_k=1))
    assert len(found) == 1
    assert found[0].chunk_id == "agpl:network"


def test_retrieval_honours_filters():
    retriever = InMemoryReferenceRetriever(CHUNKS, "2026-08-14.1")
    found = asyncio.run(retriever.retrieve("라이선스", filters={"family": "permissive"}))
    assert [c.chunk_id for c in found] == ["mit:notice"]


def test_unavailable_corpus_raises_a_typed_provider_failure():
    retriever = InMemoryReferenceRetriever(CHUNKS, "2026-08-14.1", available=False)
    with pytest.raises(ProviderFailureError) as caught:
        asyncio.run(retriever.retrieve("무엇이든"))
    assert caught.value.provider == "RAG_ENGINE"
    assert caught.value.retryable is True


def test_corpus_version_is_exposed_for_result_versioning():
    assert InMemoryReferenceRetriever([], "2026-08-14.3").corpus_version == "2026-08-14.3"


# --------------------------------------------------------------- 매니페스트


def test_repository_manifest_is_valid():
    manifest = load_manifest(CORPUS_ROOT / "manifest.yaml")
    CorpusVersion.parse(manifest.corpus_version)
    assert manifest.validate_for_ingestion()


def test_ingestion_uploads_every_approved_source():
    uploader = InMemoryCorpusUploader()
    report = asyncio.run(ingest(CORPUS_ROOT / "manifest.yaml", uploader))
    assert report.is_clean
    assert report.uploaded == len(report.prepared) > 0
    assert uploader.corpus_version == report.corpus_version


def test_unapproved_source_is_not_ingested():
    manifest = CorpusManifest.model_validate(
        {
            "corpus_version": "2026-08-14.1",
            "sources": [
                {
                    "source_id": "draft",
                    "version": "2026-08-14",
                    "source_type": "OBLIGATION_GUIDE",
                    "canonical_reference": "https://example.org",
                    "checksum": "sha256:x",
                    "approved_for_rag": False,
                }
            ],
        }
    )
    assert manifest.approved_sources == []
    with pytest.raises(ManifestError):
        manifest.validate_for_ingestion()


def test_private_source_type_is_rejected():
    # corpus 에는 참조 지식만 들어간다. 프로젝트 원문 종류는 스키마가 막는다.
    with pytest.raises(Exception):
        CorpusManifest.model_validate(
            {
                "corpus_version": "2026-08-14.1",
                "sources": [
                    {
                        "source_id": "leak",
                        "version": "1",
                        "source_type": "PRIVATE_PROJECT_SOURCE",
                        "canonical_reference": "internal",
                        "checksum": "sha256:x",
                        "approved_for_rag": True,
                    }
                ],
            }
        )


def test_checksum_mismatch_stops_ingestion(tmp_path: Path):
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "a.md").write_text("실제 내용", encoding="utf-8")
    (tmp_path / "manifest.yaml").write_text(
        """
corpus_version: 2026-08-14.1
sources:
  - source_id: a
    version: "1"
    source_type: OBLIGATION_GUIDE
    canonical_reference: https://example.org
    checksum: sha256:wrong
    path: sources/a.md
    approved_for_rag: true
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="checksum mismatch"):
        asyncio.run(ingest(tmp_path / "manifest.yaml", InMemoryCorpusUploader()))


def test_path_escaping_the_corpus_is_rejected(tmp_path: Path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("바깥 파일", encoding="utf-8")
    (tmp_path / "manifest.yaml").write_text(
        f"""
corpus_version: 2026-08-14.1
sources:
  - source_id: escape
    version: "1"
    source_type: OBLIGATION_GUIDE
    canonical_reference: https://example.org
    checksum: {checksum("바깥 파일")}
    path: ../outside.md
    approved_for_rag: true
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="outside"):
        asyncio.run(ingest(tmp_path / "manifest.yaml", InMemoryCorpusUploader()))


# --------------------------------------------------------------- 통합


def test_facade_runs_license_analysis_with_rag_evidence():
    from ip_risk_agent.intelligence.license.package_metadata import (
        StaticPackageMetadataProvider,
    )
    from ip_risk_agent.intelligence.public import (
        IntelligenceFacade,
        create_analyzer_registry,
    )

    from test_license import FakeExplainer, make_artifact

    facade = IntelligenceFacade(
        create_analyzer_registry(
            metadata_provider=StaticPackageMetadataProvider(
                {("pypi", "pymupdf"): "AGPL-3.0-only"}
            ),
            model_client=None,  # 라이선스 경로는 모델 클라이언트를 쓰지 않는다
            retriever=InMemoryReferenceRetriever(CHUNKS, "2026-08-14.1"),
            explainer=FakeExplainer(),
        )
    )
    artifact = make_artifact("PyMuPDF==1.24.0")
    assert facade.supports(artifact)

    results = asyncio.run(facade.analyze(artifact))
    assert len(results) == 1
    assert results[0].versions.rag_corpus_version == "2026-08-14.1"
    rag_evidence = [e.evidence_id for e in results[0].evidence if e.evidence_id.startswith("rag:")]
    assert rag_evidence
    # AGPL 분석이므로 AGPL 문서만 근거로 붙는다. 검색이 함께 돌려준 MIT 고지
    # 문서는 주제가 달라 제외되어야 한다 — 틀린 근거는 없는 것보다 나쁘다.
    assert any("agpl" in e for e in rag_evidence)
    assert not any("mit:notice" in e for e in rag_evidence)
