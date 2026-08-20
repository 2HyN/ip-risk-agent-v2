"""corpus 적재.

매니페스트를 읽고 → 승인 여부를 확인하고 → 자료를 읽어 → 정규화하고 → 올린다
(Agent 3 Spec 36).

비공개 작업공간 자료를 corpus 에 넣는 기능은 만들지 않는다. 실수로도 들어갈 수 없게
매니페스트에 없는 경로는 아예 읽지 않는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .corpus_manifest import CorpusManifest, CorpusSource, ManifestError, load_manifest
from .versioning import CorpusVersion


@dataclass(frozen=True)
class PreparedDocument:
    """적재 직전의 문서 하나."""

    source_id: str
    version: str
    text: str
    canonical_reference: str
    metadata: dict[str, str] = field(default_factory=dict)


class CorpusUploader(Protocol):
    """실제 업로드 대상. RAG Engine 이거나 로컬 색인이다."""

    async def upload(self, documents: list[PreparedDocument], corpus_version: str) -> int:
        ...


@dataclass
class IngestionReport:
    """적재 결과. 무엇을 넣었고 무엇을 건너뛰었는지 남긴다."""

    corpus_version: str
    prepared: list[PreparedDocument] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    uploaded: int = 0

    @property
    def is_clean(self) -> bool:
        return not self.skipped


def checksum(text: str) -> str:
    """매니페스트에 적힌 값과 대조할 지문."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_source(source: CorpusSource, root: Path) -> PreparedDocument:
    """자료를 읽고 지문을 확인한다.

    지문이 다르면 매니페스트가 가리키는 것과 다른 자료다. 조용히 넣으면
    corpus 버전이 실제 내용을 설명하지 못하게 된다.
    """
    if not source.path:
        raise ManifestError(f"{source.source_id!r} has no path to ingest")

    target = (root / source.path).resolve()
    # 매니페스트가 corpus 밖을 가리키지 못하게 한다.
    if not target.is_relative_to(root.resolve()):
        raise ManifestError(f"{source.source_id!r} points outside the corpus directory")
    if not target.is_file():
        raise ManifestError(f"{source.source_id!r} file not found: {source.path}")

    text = target.read_text(encoding="utf-8").strip()
    actual = checksum(text)
    if source.checksum != actual:
        raise ManifestError(
            f"{source.source_id!r} checksum mismatch; manifest says {source.checksum}, "
            f"file is {actual}"
        )

    return PreparedDocument(
        source_id=source.source_id,
        version=source.version,
        text=text,
        canonical_reference=source.canonical_reference,
        metadata={
            "source_type": source.source_type,
            "jurisdiction": source.jurisdiction or "",
            "tags": ",".join(source.tags),
        },
    )


async def ingest(
    manifest_path: Path,
    uploader: CorpusUploader,
    *,
    strict: bool = True,
) -> IngestionReport:
    """매니페스트를 따라 corpus 를 채운다.

    ``strict`` 이면 자료 하나가 어긋나도 전체를 중단한다. 부분 적재된 corpus 는
    버전이 내용을 설명하지 못하므로 기본값은 중단이다.
    """
    manifest: CorpusManifest = load_manifest(manifest_path)
    CorpusVersion.parse(manifest.corpus_version)  # 형식 검증
    approved = manifest.validate_for_ingestion()

    root = manifest_path.parent
    report = IngestionReport(corpus_version=manifest.corpus_version)

    for source in approved:
        try:
            report.prepared.append(prepare_source(source, root))
        except ManifestError as exc:
            if strict:
                raise
            report.skipped.append((source.source_id, str(exc)))

    report.uploaded = await uploader.upload(report.prepared, manifest.corpus_version)
    return report


class InMemoryCorpusUploader:
    """테스트와 로컬 확인용. 올린 것을 그대로 들고 있는다."""

    def __init__(self) -> None:
        self.documents: list[PreparedDocument] = []
        self.corpus_version: str | None = None

    async def upload(self, documents: list[PreparedDocument], corpus_version: str) -> int:
        self.documents = list(documents)
        self.corpus_version = corpus_version
        return len(documents)
