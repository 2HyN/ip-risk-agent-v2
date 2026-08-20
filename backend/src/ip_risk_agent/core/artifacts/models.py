"""Canonical Artifact and ArtifactState models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from iprisk_contracts import AnalysisType, SourceType

from ip_risk_agent.core.common import (
    DomainInvariantError,
    freeze_safe_mapping,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class ArtifactStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ArtifactAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    source_type: SourceType
    source_artifact_id: str
    display_name: str
    logical_path: str
    status: ArtifactStatus
    first_seen_at: datetime
    last_seen_at: datetime
    original_locator_metadata_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "risk_workspace_id",
            "mount_id",
            "source_workspace_id",
            "source_artifact_id",
            "display_name",
            "logical_path",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), f"artifact.{field_name}"),
            )
        first_seen_at = normalize_utc(self.first_seen_at, "artifact.first_seen_at")
        last_seen_at = normalize_utc(self.last_seen_at, "artifact.last_seen_at")
        require_chronological(
            first_seen_at,
            last_seen_at,
            earlier_name="artifact.first_seen_at",
            later_name="artifact.last_seen_at",
        )
        object.__setattr__(self, "first_seen_at", first_seen_at)
        object.__setattr__(self, "last_seen_at", last_seen_at)
        object.__setattr__(
            self,
            "original_locator_metadata_safe",
            freeze_safe_mapping(
                self.original_locator_metadata_safe,
                "artifact.original_locator_metadata_safe",
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactState:
    artifact_id: str
    latest_revision: str | None
    latest_checksum: str | None
    availability_state: ArtifactAvailability
    updated_at: datetime
    latest_successful_analysis_revision_by_type: Mapping[AnalysisType, str] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_id",
            require_non_empty(self.artifact_id, "artifact_state.artifact_id"),
        )
        object.__setattr__(
            self,
            "updated_at",
            normalize_utc(self.updated_at, "artifact_state.updated_at"),
        )
        revisions: dict[AnalysisType, str] = {}
        for analysis_type, revision in self.latest_successful_analysis_revision_by_type.items():
            if not isinstance(analysis_type, AnalysisType):
                raise DomainInvariantError(
                    "artifact_state analysis revision keys must be AnalysisType values"
                )
            revisions[analysis_type] = require_non_empty(
                revision,
                "artifact_state.latest_successful_analysis_revision_by_type revision",
            )
        object.__setattr__(
            self,
            "latest_successful_analysis_revision_by_type",
            MappingProxyType(revisions),
        )
