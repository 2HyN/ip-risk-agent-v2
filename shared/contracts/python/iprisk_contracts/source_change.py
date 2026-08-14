"""Content-free source change event contract."""

from typing import Literal

from pydantic import AwareDatetime

from .common import ChangeType, SafeMetadata, SourceArtifactRef, SourceType, StrictModel


class SourceChange(StrictModel):
    contract_version: Literal["1"]
    event_id: str
    provider_event_id: str | None = None
    event_fingerprint: str
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    source_type: SourceType
    artifact: SourceArtifactRef
    previous_artifact: SourceArtifactRef | None = None
    change_type: ChangeType
    revision: str | None = None
    previous_revision: str | None = None
    observed_at: AwareDatetime
    safe_metadata: SafeMetadata
