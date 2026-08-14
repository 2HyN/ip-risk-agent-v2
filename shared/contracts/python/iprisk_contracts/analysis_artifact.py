"""Security-gated analysis input contract."""

from typing import Literal

from pydantic import AwareDatetime

from .common import (
    AnalysisSecurityContext,
    AnalysisType,
    ArtifactKind,
    ContentScope,
    StrictModel,
    TextSegment,
)


class AnalysisArtifact(StrictModel):
    contract_version: Literal["1"]
    analysis_job_id: str
    risk_workspace_id: str
    mount_id: str
    artifact_id: str
    logical_path: str
    revision: str
    artifact_kind: ArtifactKind
    mime_type: str | None = None
    requested_analyzers: list[AnalysisType]
    content_scope: ContentScope
    text_segments: list[TextSegment]
    security_context: AnalysisSecurityContext
    created_at: AwareDatetime

    def require_approved(self) -> "AnalysisArtifact":
        if not self.security_context.approved:
            raise PermissionError("analysis artifact has not passed the Security Gate")
        return self
