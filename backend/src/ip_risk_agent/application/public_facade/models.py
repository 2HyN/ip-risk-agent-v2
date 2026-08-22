"""Persistence-neutral DTOs exposed only through the Control Plane facade."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from iprisk_contracts import (
    AnalysisArtifact,
    AnalysisType,
    MountRef,
    SourceAccessReceipt,
    SourceArtifactRef,
    SourceChange,
    SourceType,
)

from ip_risk_agent.application.risk_reconcile import EvidenceRetentionPolicy
from ip_risk_agent.application.security_gate import SecurityGatePolicy
from ip_risk_agent.core.common import (
    DomainInvariantError,
    freeze_safe_mapping,
    require_non_empty,
)

_SENSITIVE_KEY = re.compile(
    r"(?i)(?:access[_-]?key|api[_-]?key|authorization|client[_-]?secret|"
    r"credential(?![_-]?ref)|password|private[_-]?key|refresh[_-]?token|secret|token)"
)


class PublicVwsAction(StrEnum):
    VWS_VIEW = "VWS_VIEW"
    RISK_VIEW = "RISK_VIEW"
    RISK_REVIEW = "RISK_REVIEW"
    SOURCE_MOUNT = "SOURCE_MOUNT"
    MOUNT_STATUS_VIEW = "MOUNT_STATUS_VIEW"
    MOUNT_RENAME = "MOUNT_RENAME"
    MOUNT_SOURCE_OPERATION = "MOUNT_SOURCE_OPERATION"
    MOUNT_RECONNECT = "MOUNT_RECONNECT"
    MOUNT_SCOPE_MANAGE = "MOUNT_SCOPE_MANAGE"
    MOUNT_DISABLE = "MOUNT_DISABLE"
    MOUNT_REMOVE = "MOUNT_REMOVE"
    VWS_SECURITY_MANAGE = "VWS_SECURITY_MANAGE"
    MEMBER_MANAGE = "MEMBER_MANAGE"
    AUDIT_VIEW = "AUDIT_VIEW"
    AUDIT_EXPORT = "AUDIT_EXPORT"
    WORKSPACE_DELETE = "WORKSPACE_DELETE"
    OWNERSHIP_TRANSFER = "OWNERSHIP_TRANSFER"


@dataclass(frozen=True, slots=True)
class SecurityGatePolicyConfig:
    max_input_bytes: int = 2_000_000
    max_output_bytes: int = 256_000
    max_segments: int = 64
    max_segment_bytes: int = 32_000
    document_full_text_bytes: int = 128_000
    allow_text_patent: bool = True
    denied_mime_prefixes: tuple[str, ...] = (
        "audio/",
        "font/",
        "image/",
        "video/",
    )
    denied_mime_types: tuple[str, ...] = (
        "application/gzip",
        "application/octet-stream",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/zip",
    )

    def _build(self, policy_version: str) -> SecurityGatePolicy:
        return SecurityGatePolicy(
            policy_version=policy_version,
            max_input_bytes=self.max_input_bytes,
            max_output_bytes=self.max_output_bytes,
            max_segments=self.max_segments,
            max_segment_bytes=self.max_segment_bytes,
            document_full_text_bytes=self.document_full_text_bytes,
            allow_text_patent=self.allow_text_patent,
            denied_mime_prefixes=self.denied_mime_prefixes,
            denied_mime_types=self.denied_mime_types,
        )


@dataclass(frozen=True, slots=True)
class EvidenceRetentionConfig:
    max_excerpt_chars: int = 1_000
    max_reference_chars: int = 2_048
    max_metadata_chars: int = 256
    max_metadata_items: int = 32
    max_metadata_depth: int = 4
    max_metadata_json_bytes: int = 4_096
    max_summary_chars: int = 300
    max_failure_message_chars: int = 512

    def _build(self) -> EvidenceRetentionPolicy:
        return EvidenceRetentionPolicy(
            max_excerpt_chars=self.max_excerpt_chars,
            max_reference_chars=self.max_reference_chars,
            max_metadata_chars=self.max_metadata_chars,
            max_metadata_items=self.max_metadata_items,
            max_metadata_depth=self.max_metadata_depth,
            max_metadata_json_bytes=self.max_metadata_json_bytes,
            max_summary_chars=self.max_summary_chars,
            max_failure_message_chars=self.max_failure_message_chars,
        )


@dataclass(frozen=True, slots=True)
class ControlPlaneFacadeConfig:
    requested_analysis_types: tuple[AnalysisType, ...] = (
        AnalysisType.PATENT,
        AnalysisType.LICENSE,
    )
    retry_failed_events: bool = True
    concurrency_attempts: int = 3
    analysis_lease_seconds: int = 300
    security_gate: SecurityGatePolicyConfig = field(
        default_factory=SecurityGatePolicyConfig
    )
    evidence_retention: EvidenceRetentionConfig = field(
        default_factory=EvidenceRetentionConfig
    )

    def __post_init__(self) -> None:
        requested = tuple(
            sorted(set(self.requested_analysis_types), key=lambda value: value.value)
        )
        if not requested:
            raise DomainInvariantError("requested_analysis_types must not be empty")
        if self.concurrency_attempts < 1:
            raise DomainInvariantError("concurrency_attempts must be positive")
        if not 1 <= self.analysis_lease_seconds <= 3_600:
            raise DomainInvariantError(
                "analysis_lease_seconds must be between 1 and 3600"
            )
        self.security_gate._build("facade-config-validation")
        self.evidence_retention._build()
        object.__setattr__(self, "requested_analysis_types", requested)


@dataclass(frozen=True, slots=True)
class FacadeAuthorizationDecision:
    allowed: bool
    reason: str
    provider_authority_required: bool


@dataclass(frozen=True, slots=True)
class SourceMetadataRegistrationCommand:
    registration_key: str
    actor_user_id: str
    risk_workspace_id: str
    source_type: SourceType
    connection_key: str
    source_workspace_key: str
    external_scope_id: str
    source_workspace_display_name: str
    mount_alias: str
    provider_subject: str | None = None
    provider_account_label: str | None = None
    credential_ref: str | None = field(default=None, repr=False)
    tracking_config_safe: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "registration_key",
            "actor_user_id",
            "risk_workspace_id",
            "connection_key",
            "source_workspace_key",
            "external_scope_id",
            "source_workspace_display_name",
            "mount_alias",
        ):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), f"source_metadata.{name}"),
            )
        if self.credential_ref is not None:
            reference = require_non_empty(
                self.credential_ref,
                "source_metadata.credential_ref",
            )
            if len(reference) > 512 or any(character.isspace() for character in reference):
                raise DomainInvariantError(
                    "source_metadata.credential_ref must be a compact opaque reference"
                )
            object.__setattr__(self, "credential_ref", reference)
        tracking = freeze_safe_mapping(
            self.tracking_config_safe,
            "source_metadata.tracking_config_safe",
        )
        _reject_sensitive_keys(tracking)
        object.__setattr__(self, "tracking_config_safe", tracking)


@dataclass(frozen=True, slots=True)
class SourceMetadataRegistration:
    connection_id: str
    source_workspace_id: str
    mount_id: str
    created_connection: bool
    created_source_workspace: bool
    created_mount: bool


@dataclass(frozen=True, slots=True)
class SourceAccessReceiptContext:
    risk_workspace_id: str
    mount_id: str
    source_workspace_id: str
    source_type: SourceType
    source_artifact_id: str
    revision: str
    receipt: SourceAccessReceipt
    analysis_job_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "risk_workspace_id",
            "mount_id",
            "source_workspace_id",
            "source_artifact_id",
            "revision",
        ):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), f"source_access.{name}"),
            )
        if self.analysis_job_id is not None:
            object.__setattr__(
                self,
                "analysis_job_id",
                require_non_empty(self.analysis_job_id, "source_access.analysis_job_id"),
            )


@dataclass(frozen=True, slots=True)
class SourceAccessRegistration:
    source_access_event_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class SourceChangeReceipt:
    change_event_id: str
    artifact_id: str
    analysis_job_id: str | None
    disposition: str
    enqueued: bool


@dataclass(frozen=True, slots=True)
class SourceScopeInput:
    in_scope: bool = True
    ignore_text: str = ""
    denial_code_safe: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisExecutionClaim:
    change_event_id: str
    analysis_job_id: str
    artifact_id: str
    revision: str
    requested_analysis_types: tuple[AnalysisType, ...]
    attempt: int
    lease_expires_at: datetime
    source_change: SourceChange


@dataclass(frozen=True, slots=True)
class AnalysisArtifactBuildResult:
    analysis_artifact: AnalysisArtifact | None
    denial_reason: str | None
    source_access_event_id: str

    @property
    def approved(self) -> bool:
        return self.analysis_artifact is not None


@dataclass(frozen=True, slots=True)
class AnalysisResultReceipt:
    disposition: str
    analysis_job_id: str
    result_fingerprint: str
    job_status: str
    affected_risk_ids: tuple[str, ...]
    resolved_risk_ids: tuple[str, ...]
    evidence_count: int


@dataclass(frozen=True, slots=True)
class SourceWorkspaceContext:
    source_workspace_id: str
    source_connection_id: str
    source_type: SourceType
    external_scope_id: str
    display_name: str
    source_workspace_status: str
    source_connection_status: str
    authorized_by_user_id: str
    provider_account_label: str | None
    credential_ref: str | None = field(default=None, repr=False)
    tracking_config_safe: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OriginalSourceRequest:
    requested_by_user_id: str
    mount: MountRef
    artifact: SourceArtifactRef
    provider_authority_required: bool = True


def _reject_sensitive_keys(value: Mapping[str, object]) -> None:
    for key, item in value.items():
        if _SENSITIVE_KEY.search(key):
            raise DomainInvariantError(
                "source_metadata.tracking_config_safe contains a sensitive key"
            )
        if isinstance(item, Mapping):
            _reject_sensitive_keys(item)
        elif isinstance(item, tuple):
            for nested in item:
                if isinstance(nested, Mapping):
                    _reject_sensitive_keys(nested)


__all__ = [
    "AnalysisArtifactBuildResult",
    "AnalysisExecutionClaim",
    "AnalysisResultReceipt",
    "ControlPlaneFacadeConfig",
    "EvidenceRetentionConfig",
    "FacadeAuthorizationDecision",
    "OriginalSourceRequest",
    "PublicVwsAction",
    "SecurityGatePolicyConfig",
    "SourceAccessReceiptContext",
    "SourceAccessRegistration",
    "SourceChangeReceipt",
    "SourceMetadataRegistration",
    "SourceMetadataRegistrationCommand",
    "SourceScopeInput",
    "SourceWorkspaceContext",
]


@dataclass(frozen=True, slots=True)
class UntrackedArtifact:
    """추적을 끊은 결과.

    ``source_artifact_id`` 는 호출자(connector)가 provider 쪽 감시를 마저 끊는 데
    쓴다. ``already_archived`` 가 참이면 이미 해제된 것을 다시 부른 것이므로 화면이
    오류를 낼 이유가 없다.
    """

    artifact_id: str
    mount_id: str
    source_artifact_id: str
    excluded_risk_ids: tuple[str, ...]
    already_archived: bool
