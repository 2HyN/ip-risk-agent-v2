"""RAG corpus 매니페스트.

corpus 에는 참조 지식만 넣는다. 비공개 저장소나 Drive 문서 원문은 넣지 않는다
(Blueprint 19). 그 경계를 문서가 아니라 코드로 지킨다.

형식은 명세(Agent 3 Spec 34)대로 YAML 이다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 참조 지식으로 허용하는 자료 종류. 여기 없는 것은 corpus 에 들어갈 수 없다.
ALLOWED_SOURCE_TYPES = frozenset(
    {"SPDX_REFERENCE", "OSS_LICENSE_TEXT", "OBLIGATION_GUIDE", "IP_POLICY_REFERENCE"}
)


class ManifestError(ValueError):
    """매니페스트가 규칙을 어겼다."""


class CorpusSource(BaseModel):
    """ingestion 대상 하나."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    version: str
    source_type: str
    canonical_reference: str
    checksum: str
    tags: list[str] = Field(default_factory=list)
    # 이 문서가 실제로 다루는 SPDX 식별자. 참조 게이트가 주제 일치를 판정할 때
    # 쓰며, 배포 validator 가 코드의 커버리지 표와 교차 검증한다.
    covers: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    approved_for_rag: bool = False
    path: str | None = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: str) -> str:
        if value not in ALLOWED_SOURCE_TYPES:
            raise ValueError(
                f"{value!r} is not an allowed source type; "
                f"expected one of {sorted(ALLOWED_SOURCE_TYPES)}"
            )
        return value


class CorpusManifest(BaseModel):
    """corpus 한 판. version 이 AnalysisResult 에 기록된다."""

    model_config = ConfigDict(extra="forbid")

    corpus_version: str
    description: str = ""
    sources: list[CorpusSource] = Field(default_factory=list)

    @property
    def approved_sources(self) -> list[CorpusSource]:
        """승인된 것만 ingestion 대상이다."""
        return [source for source in self.sources if source.approved_for_rag]

    def validate_for_ingestion(self) -> list[CorpusSource]:
        """실제로 넣기 전에 확인한다. 하나라도 어긋나면 전체를 중단한다."""
        approved = self.approved_sources
        if not approved:
            raise ManifestError("no source is approved for RAG ingestion")

        seen: set[str] = set()
        for source in approved:
            if source.source_id in seen:
                raise ManifestError(f"duplicate source_id: {source.source_id!r}")
            seen.add(source.source_id)
            if not source.checksum:
                raise ManifestError(f"{source.source_id!r} is missing a checksum")
        return approved


def load_manifest(path: Path) -> CorpusManifest:
    """매니페스트 파일을 읽는다.

    ``safe_load`` 를 쓴다. corpus 정의가 임의 객체를 만들어 낼 수 있으면 안 된다.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestError(f"{path.name} must contain a mapping at the top level")
    return CorpusManifest.model_validate(document)
