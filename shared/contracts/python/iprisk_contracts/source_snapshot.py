"""Transient source snapshot contract."""

from typing import Literal

from pydantic import AwareDatetime, Field

from .common import (
    ArtifactKind,
    ContentScope,
    SourceAccessReceipt,
    SourceType,
    StrictModel,
    TextSegment,
)


class SourceSnapshot(StrictModel):
    contract_version: Literal["1"]
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    source_type: SourceType
    source_artifact_id: str
    resolved_revision: str
    retrieved_at: AwareDatetime
    display_name: str
    logical_path_hint: str | None = None
    mime_type: str | None = None
    artifact_kind: ArtifactKind
    content_scope: ContentScope
    text_segments: list[TextSegment]
    checksum: str
    byte_size: int = Field(ge=0)
    source_access_receipt: SourceAccessReceipt
