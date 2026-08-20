"""Strict domain-to-Firestore document mappers for all canonical records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from iprisk_contracts import (
    AnalysisCoverage,
    AnalysisStatus,
    AnalysisType,
    ChangeType,
    ReviewPriority,
    SourceAccessType,
    SourceType,
)
from ip_risk_agent.application.analysis_jobs.models import (
    AnalysisJob,
    AnalysisJobStatus,
    AnalysisOutcome,
    ProviderFailureSummary,
)
from ip_risk_agent.application.process_change.models import ChangeEvent, ChangeEventStatus
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
from ip_risk_agent.core.auth import User, UserStatus
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    Membership,
    MembershipInvitation,
    MembershipRole,
    MembershipStatus,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
    mount_alias_key,
)
from ip_risk_agent.core.notifications import (
    Notification,
    NotificationStatus,
    NotificationType,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskEvidence,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace, RiskWorkspaceStatus

from .schema import DOCUMENT_SCHEMA_VERSION

Document = dict[str, Any]


class DocumentMappingError(ValueError):
    """Raised when a stored document is not the strict canonical shape."""


def _thaw(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _thaw(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(nested) for nested in value]
    return value


def _document(record_kind: str, **fields: object) -> Document:
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "record_kind": record_kind,
        **{name: _thaw(value) for name, value in fields.items()},
    }


def _require_shape(
    document: Mapping[str, object],
    *,
    record_kind: str,
    fields: tuple[str, ...],
) -> dict[str, object]:
    expected = {"schema_version", "record_kind", *fields}
    actual = set(document)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DocumentMappingError(
            f"invalid {record_kind} document fields; missing={missing}, extra={extra}"
        )
    if document["schema_version"] != DOCUMENT_SCHEMA_VERSION:
        raise DocumentMappingError(
            f"unsupported {record_kind} schema version: {document['schema_version']!r}"
        )
    if document["record_kind"] != record_kind:
        raise DocumentMappingError(
            f"expected record_kind={record_kind!r}, got {document['record_kind']!r}"
        )
    return dict(document)


def user_to_document(value: User) -> Document:
    return _document(
        "user",
        id=value.id,
        google_subject=value.google_subject,
        email=value.email,
        display_name=value.display_name,
        avatar_url=value.avatar_url,
        created_at=value.created_at,
        last_login_at=value.last_login_at,
        status=value.status,
        session_version=value.session_version,
    )


def user_from_document(document: Mapping[str, object]) -> User:
    data = _require_shape(
        document,
        record_kind="user",
        fields=(
            "id",
            "google_subject",
            "email",
            "display_name",
            "avatar_url",
            "created_at",
            "last_login_at",
            "status",
            "session_version",
        ),
    )
    return User(
        id=str(data["id"]),
        google_subject=str(data["google_subject"]),
        email=str(data["email"]),
        display_name=str(data["display_name"]),
        avatar_url=_optional_str(data["avatar_url"]),
        created_at=_datetime(data["created_at"]),
        last_login_at=_datetime(data["last_login_at"]),
        status=UserStatus(data["status"]),
        session_version=_int(data["session_version"]),
    )


def workspace_to_document(value: RiskWorkspace) -> Document:
    return _document(
        "risk_workspace",
        id=value.id,
        name=value.name,
        description=value.description,
        owner_user_id=value.owner_user_id,
        security_policy_version=value.security_policy_version,
        retention_policy_version=value.retention_policy_version,
        created_at=value.created_at,
        updated_at=value.updated_at,
        status=value.status,
        global_ignore_text=value.global_ignore_text,
    )


def workspace_from_document(document: Mapping[str, object]) -> RiskWorkspace:
    data = _require_shape(
        document,
        record_kind="risk_workspace",
        fields=(
            "id",
            "name",
            "description",
            "owner_user_id",
            "security_policy_version",
            "retention_policy_version",
            "created_at",
            "updated_at",
            "status",
            "global_ignore_text",
        ),
    )
    return RiskWorkspace(
        id=str(data["id"]),
        name=str(data["name"]),
        description=_optional_str(data["description"]),
        owner_user_id=str(data["owner_user_id"]),
        security_policy_version=str(data["security_policy_version"]),
        retention_policy_version=str(data["retention_policy_version"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        status=RiskWorkspaceStatus(data["status"]),
        global_ignore_text=str(data["global_ignore_text"]),
    )


def membership_to_document(value: Membership) -> Document:
    return _document(
        "membership",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        user_id=value.user_id,
        role=value.role,
        status=value.status,
        invited_by=value.invited_by,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def membership_from_document(document: Mapping[str, object]) -> Membership:
    data = _require_shape(
        document,
        record_kind="membership",
        fields=(
            "id",
            "risk_workspace_id",
            "user_id",
            "role",
            "status",
            "invited_by",
            "created_at",
            "updated_at",
        ),
    )
    return Membership(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        user_id=str(data["user_id"]),
        role=MembershipRole(data["role"]),
        status=MembershipStatus(data["status"]),
        invited_by=str(data["invited_by"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
    )


def invitation_to_document(value: MembershipInvitation) -> Document:
    return _document(
        "membership_invitation",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        email=value.email,
        role=value.role,
        status=value.status,
        invited_by=value.invited_by,
        created_at=value.created_at,
        updated_at=value.updated_at,
        expires_at=value.expires_at,
    )


def invitation_from_document(document: Mapping[str, object]) -> MembershipInvitation:
    data = _require_shape(
        document,
        record_kind="membership_invitation",
        fields=(
            "id",
            "risk_workspace_id",
            "email",
            "role",
            "status",
            "invited_by",
            "created_at",
            "updated_at",
            "expires_at",
        ),
    )
    return MembershipInvitation(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        email=str(data["email"]),
        role=MembershipRole(data["role"]),
        status=InvitationStatus(data["status"]),
        invited_by=str(data["invited_by"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        expires_at=_optional_datetime(data["expires_at"]),
    )


def source_connection_to_document(value: SourceConnection) -> Document:
    return _document(
        "source_connection",
        id=value.id,
        provider=value.provider,
        authorized_by_user_id=value.authorized_by_user_id,
        status=value.status,
        created_at=value.created_at,
        updated_at=value.updated_at,
        provider_subject=value.provider_subject,
        provider_account_label=value.provider_account_label,
        credential_ref=value.credential_ref,
    )


def source_connection_from_document(document: Mapping[str, object]) -> SourceConnection:
    data = _require_shape(
        document,
        record_kind="source_connection",
        fields=(
            "id",
            "provider",
            "authorized_by_user_id",
            "status",
            "created_at",
            "updated_at",
            "provider_subject",
            "provider_account_label",
            "credential_ref",
        ),
    )
    return SourceConnection(
        id=str(data["id"]),
        provider=SourceType(data["provider"]),
        authorized_by_user_id=str(data["authorized_by_user_id"]),
        status=SourceConnectionStatus(data["status"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        provider_subject=_optional_str(data["provider_subject"]),
        provider_account_label=_optional_str(data["provider_account_label"]),
        credential_ref=_optional_str(data["credential_ref"]),
    )


def source_workspace_to_document(value: SourceWorkspace) -> Document:
    return _document(
        "source_workspace",
        id=value.id,
        source_connection_id=value.source_connection_id,
        source_type=value.source_type,
        external_scope_id=value.external_scope_id,
        display_name=value.display_name,
        status=value.status,
        created_at=value.created_at,
        updated_at=value.updated_at,
        tracking_config_safe=value.tracking_config_safe,
    )


def source_workspace_from_document(document: Mapping[str, object]) -> SourceWorkspace:
    data = _require_shape(
        document,
        record_kind="source_workspace",
        fields=(
            "id",
            "source_connection_id",
            "source_type",
            "external_scope_id",
            "display_name",
            "status",
            "created_at",
            "updated_at",
            "tracking_config_safe",
        ),
    )
    return SourceWorkspace(
        id=str(data["id"]),
        source_connection_id=str(data["source_connection_id"]),
        source_type=SourceType(data["source_type"]),
        external_scope_id=str(data["external_scope_id"]),
        display_name=str(data["display_name"]),
        status=SourceWorkspaceStatus(data["status"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        tracking_config_safe=_mapping(data["tracking_config_safe"]),
    )


def mount_to_document(value: WorkspaceMount) -> Document:
    return _document(
        "workspace_mount",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        source_workspace_id=value.source_workspace_id,
        alias=value.alias,
        alias_key=mount_alias_key(value.alias),
        mounted_by_user_id=value.mounted_by_user_id,
        source_connection_id=value.source_connection_id,
        status=value.status,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def mount_from_document(document: Mapping[str, object]) -> WorkspaceMount:
    data = _require_shape(
        document,
        record_kind="workspace_mount",
        fields=(
            "id",
            "risk_workspace_id",
            "source_workspace_id",
            "alias",
            "alias_key",
            "mounted_by_user_id",
            "source_connection_id",
            "status",
            "created_at",
            "updated_at",
        ),
    )
    if data["alias_key"] != mount_alias_key(str(data["alias"])):
        raise DocumentMappingError("workspace_mount alias_key does not match alias")
    return WorkspaceMount(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        source_workspace_id=str(data["source_workspace_id"]),
        alias=str(data["alias"]),
        mounted_by_user_id=str(data["mounted_by_user_id"]),
        source_connection_id=str(data["source_connection_id"]),
        status=MountStatus(data["status"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
    )


def artifact_to_document(value: Artifact) -> Document:
    return _document(
        "artifact",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        mount_id=value.mount_id,
        source_workspace_id=value.source_workspace_id,
        source_type=value.source_type,
        source_artifact_id=value.source_artifact_id,
        display_name=value.display_name,
        logical_path=value.logical_path,
        status=value.status,
        first_seen_at=value.first_seen_at,
        last_seen_at=value.last_seen_at,
        original_locator_metadata_safe=value.original_locator_metadata_safe,
    )


def artifact_from_document(document: Mapping[str, object]) -> Artifact:
    data = _require_shape(
        document,
        record_kind="artifact",
        fields=(
            "id",
            "risk_workspace_id",
            "mount_id",
            "source_workspace_id",
            "source_type",
            "source_artifact_id",
            "display_name",
            "logical_path",
            "status",
            "first_seen_at",
            "last_seen_at",
            "original_locator_metadata_safe",
        ),
    )
    return Artifact(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        mount_id=str(data["mount_id"]),
        source_workspace_id=str(data["source_workspace_id"]),
        source_type=SourceType(data["source_type"]),
        source_artifact_id=str(data["source_artifact_id"]),
        display_name=str(data["display_name"]),
        logical_path=str(data["logical_path"]),
        status=ArtifactStatus(data["status"]),
        first_seen_at=_datetime(data["first_seen_at"]),
        last_seen_at=_datetime(data["last_seen_at"]),
        original_locator_metadata_safe=_mapping(data["original_locator_metadata_safe"]),
    )


def artifact_state_to_document(value: ArtifactState) -> Document:
    return _document(
        "artifact_state",
        artifact_id=value.artifact_id,
        latest_revision=value.latest_revision,
        latest_checksum=value.latest_checksum,
        availability_state=value.availability_state,
        updated_at=value.updated_at,
        latest_successful_analysis_revision_by_type={
            analysis_type.value: revision
            for analysis_type, revision in value.latest_successful_analysis_revision_by_type.items()
        },
    )


def artifact_state_from_document(document: Mapping[str, object]) -> ArtifactState:
    data = _require_shape(
        document,
        record_kind="artifact_state",
        fields=(
            "artifact_id",
            "latest_revision",
            "latest_checksum",
            "availability_state",
            "updated_at",
            "latest_successful_analysis_revision_by_type",
        ),
    )
    revisions = _mapping(data["latest_successful_analysis_revision_by_type"])
    return ArtifactState(
        artifact_id=str(data["artifact_id"]),
        latest_revision=_optional_str(data["latest_revision"]),
        latest_checksum=_optional_str(data["latest_checksum"]),
        availability_state=ArtifactAvailability(data["availability_state"]),
        updated_at=_datetime(data["updated_at"]),
        latest_successful_analysis_revision_by_type={
            AnalysisType(key): str(value) for key, value in revisions.items()
        },
    )


def change_event_to_document(value: ChangeEvent) -> Document:
    return _document(
        "change_event",
        id=value.id,
        event_fingerprint=value.event_fingerprint,
        risk_workspace_id=value.risk_workspace_id,
        mount_id=value.mount_id,
        source_workspace_id=value.source_workspace_id,
        source_artifact_id=value.source_artifact_id,
        source_type=value.source_type,
        change_type=value.change_type,
        revision=value.revision,
        previous_revision=value.previous_revision,
        observed_at=value.observed_at,
        status=value.status,
        attempts=value.attempts,
        created_at=value.created_at,
        updated_at=value.updated_at,
        artifact_id=value.artifact_id,
        provider_event_id=value.provider_event_id,
        last_error_safe=value.last_error_safe,
        safe_metadata=value.safe_metadata,
    )


def change_event_from_document(document: Mapping[str, object]) -> ChangeEvent:
    data = _require_shape(
        document,
        record_kind="change_event",
        fields=(
            "id",
            "event_fingerprint",
            "risk_workspace_id",
            "mount_id",
            "source_workspace_id",
            "source_artifact_id",
            "source_type",
            "change_type",
            "revision",
            "previous_revision",
            "observed_at",
            "status",
            "attempts",
            "created_at",
            "updated_at",
            "artifact_id",
            "provider_event_id",
            "last_error_safe",
            "safe_metadata",
        ),
    )
    return ChangeEvent(
        id=str(data["id"]),
        event_fingerprint=str(data["event_fingerprint"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        mount_id=str(data["mount_id"]),
        source_workspace_id=str(data["source_workspace_id"]),
        source_artifact_id=str(data["source_artifact_id"]),
        source_type=SourceType(data["source_type"]),
        change_type=ChangeType(data["change_type"]),
        revision=_optional_str(data["revision"]),
        previous_revision=_optional_str(data["previous_revision"]),
        observed_at=_datetime(data["observed_at"]),
        status=ChangeEventStatus(data["status"]),
        attempts=_int(data["attempts"]),
        created_at=_datetime(data["created_at"]),
        updated_at=_datetime(data["updated_at"]),
        artifact_id=_optional_str(data["artifact_id"]),
        provider_event_id=_optional_str(data["provider_event_id"]),
        last_error_safe=_optional_str(data["last_error_safe"]),
        safe_metadata=_mapping(data["safe_metadata"]),
    )


def analysis_job_to_document(value: AnalysisJob) -> Document:
    return _document(
        "analysis_job",
        id=value.id,
        change_event_id=value.change_event_id,
        artifact_id=value.artifact_id,
        revision=value.revision,
        requested_analysis_types=value.requested_analysis_types,
        status=value.status,
        created_at=value.created_at,
        started_at=value.started_at,
        completed_at=value.completed_at,
        failure_safe=value.failure_safe,
        analysis_outcomes={
            analysis_type.value: _analysis_outcome_to_value(outcome)
            for analysis_type, outcome in value.analysis_outcomes.items()
        },
    )


def analysis_job_from_document(document: Mapping[str, object]) -> AnalysisJob:
    data = _require_shape(
        document,
        record_kind="analysis_job",
        fields=(
            "id",
            "change_event_id",
            "artifact_id",
            "revision",
            "requested_analysis_types",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "failure_safe",
            "analysis_outcomes",
        ),
    )
    outcomes = _mapping(data["analysis_outcomes"])
    return AnalysisJob(
        id=str(data["id"]),
        change_event_id=str(data["change_event_id"]),
        artifact_id=str(data["artifact_id"]),
        revision=str(data["revision"]),
        requested_analysis_types=tuple(
            AnalysisType(item) for item in _list(data["requested_analysis_types"])
        ),
        status=AnalysisJobStatus(data["status"]),
        created_at=_datetime(data["created_at"]),
        started_at=_optional_datetime(data["started_at"]),
        completed_at=_optional_datetime(data["completed_at"]),
        failure_safe=_optional_str(data["failure_safe"]),
        analysis_outcomes={
            AnalysisType(key): _analysis_outcome_from_value(value)
            for key, value in outcomes.items()
        },
    )


def _analysis_outcome_to_value(value: AnalysisOutcome) -> Document:
    return {
        "analysis_type": value.analysis_type.value,
        "result_fingerprint": value.result_fingerprint,
        "status": value.status.value,
        "coverage": value.coverage.value,
        "analyzer_version": value.analyzer_version,
        "started_at": value.started_at,
        "completed_at": value.completed_at,
        "provider_failures": [
            {
                "provider": failure.provider,
                "category": failure.category,
                "retryable": failure.retryable,
                "safe_message": failure.safe_message,
            }
            for failure in value.provider_failures
        ],
        "model_id": value.model_id,
        "prompt_version": value.prompt_version,
        "policy_version": value.policy_version,
        "rag_corpus_version": value.rag_corpus_version,
    }


def _analysis_outcome_from_value(value: object) -> AnalysisOutcome:
    data = _mapping(value)
    expected = {
        "analysis_type",
        "result_fingerprint",
        "status",
        "coverage",
        "analyzer_version",
        "started_at",
        "completed_at",
        "provider_failures",
        "model_id",
        "prompt_version",
        "policy_version",
        "rag_corpus_version",
    }
    if set(data) != expected:
        raise DocumentMappingError("invalid analysis outcome fields")
    failures: list[ProviderFailureSummary] = []
    for raw_failure in _list(data["provider_failures"]):
        failure = _mapping(raw_failure)
        if set(failure) != {"provider", "category", "retryable", "safe_message"}:
            raise DocumentMappingError("invalid provider failure summary fields")
        retryable = failure["retryable"]
        if not isinstance(retryable, bool):
            raise DocumentMappingError("provider failure retryable must be boolean")
        failures.append(
            ProviderFailureSummary(
                provider=str(failure["provider"]),
                category=str(failure["category"]),
                retryable=retryable,
                safe_message=str(failure["safe_message"]),
            )
        )
    return AnalysisOutcome(
        analysis_type=AnalysisType(data["analysis_type"]),
        result_fingerprint=str(data["result_fingerprint"]),
        status=AnalysisStatus(data["status"]),
        coverage=AnalysisCoverage(data["coverage"]),
        analyzer_version=str(data["analyzer_version"]),
        started_at=_datetime(data["started_at"]),
        completed_at=_datetime(data["completed_at"]),
        provider_failures=tuple(failures),
        model_id=_optional_str(data["model_id"]),
        prompt_version=_optional_str(data["prompt_version"]),
        policy_version=_optional_str(data["policy_version"]),
        rag_corpus_version=_optional_str(data["rag_corpus_version"]),
    )


def risk_to_document(value: Risk) -> Document:
    return _document(
        "risk",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        artifact_id=value.artifact_id,
        analysis_type=value.analysis_type,
        risk_key=value.risk_key,
        lifecycle_state=value.lifecycle_state,
        review_disposition=value.review_disposition,
        review_priority=value.review_priority,
        summary=value.summary,
        first_seen_at=value.first_seen_at,
        last_seen_at=value.last_seen_at,
        latest_analysis_job_id=value.latest_analysis_job_id,
        updated_at=value.updated_at,
        resolved_at=value.resolved_at,
        latest_evidence_revision=value.latest_evidence_revision,
        review_version=value.review_version,
    )


def risk_from_document(document: Mapping[str, object]) -> Risk:
    data = _require_shape(
        document,
        record_kind="risk",
        fields=(
            "id",
            "risk_workspace_id",
            "artifact_id",
            "analysis_type",
            "risk_key",
            "lifecycle_state",
            "review_disposition",
            "review_priority",
            "summary",
            "first_seen_at",
            "last_seen_at",
            "latest_analysis_job_id",
            "updated_at",
            "resolved_at",
            "latest_evidence_revision",
            "review_version",
        ),
    )
    return Risk(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        artifact_id=str(data["artifact_id"]),
        analysis_type=AnalysisType(data["analysis_type"]),
        risk_key=str(data["risk_key"]),
        lifecycle_state=RiskLifecycleState(data["lifecycle_state"]),
        review_disposition=ReviewDisposition(data["review_disposition"]),
        review_priority=ReviewPriority(data["review_priority"]),
        summary=str(data["summary"]),
        first_seen_at=_datetime(data["first_seen_at"]),
        last_seen_at=_datetime(data["last_seen_at"]),
        latest_analysis_job_id=str(data["latest_analysis_job_id"]),
        updated_at=_datetime(data["updated_at"]),
        resolved_at=_optional_datetime(data["resolved_at"]),
        latest_evidence_revision=_optional_str(data["latest_evidence_revision"]),
        review_version=_int(data["review_version"]),
    )


def risk_evidence_to_document(value: RiskEvidence) -> Document:
    return _document(
        "risk_evidence",
        id=value.id,
        risk_id=value.risk_id,
        analysis_job_id=value.analysis_job_id,
        evidence_id_from_result=value.evidence_id_from_result,
        evidence_type=value.evidence_type,
        excerpt=value.excerpt,
        reference=value.reference,
        source_revision=value.source_revision,
        created_at=value.created_at,
        metadata_safe=value.metadata_safe,
    )


def risk_evidence_from_document(document: Mapping[str, object]) -> RiskEvidence:
    data = _require_shape(
        document,
        record_kind="risk_evidence",
        fields=(
            "id",
            "risk_id",
            "analysis_job_id",
            "evidence_id_from_result",
            "evidence_type",
            "excerpt",
            "reference",
            "source_revision",
            "created_at",
            "metadata_safe",
        ),
    )
    return RiskEvidence(
        id=str(data["id"]),
        risk_id=str(data["risk_id"]),
        analysis_job_id=str(data["analysis_job_id"]),
        evidence_id_from_result=str(data["evidence_id_from_result"]),
        evidence_type=str(data["evidence_type"]),
        excerpt=str(data["excerpt"]),
        reference=str(data["reference"]),
        source_revision=str(data["source_revision"]),
        created_at=_datetime(data["created_at"]),
        metadata_safe=_mapping(data["metadata_safe"]),
    )


def risk_event_to_document(value: RiskEvent) -> Document:
    return _document(
        "risk_event",
        id=value.id,
        risk_id=value.risk_id,
        event_type=value.event_type,
        actor_type=value.actor_type,
        occurred_at=value.occurred_at,
        actor_user_id=value.actor_user_id,
        previous_state_safe=value.previous_state_safe,
        new_state_safe=value.new_state_safe,
        analysis_job_id=value.analysis_job_id,
        evidence_refs=value.evidence_refs,
        reason_safe=value.reason_safe,
        previous_event_hash=value.previous_event_hash,
        event_hash=value.event_hash,
    )


def risk_event_from_document(document: Mapping[str, object]) -> RiskEvent:
    data = _require_shape(
        document,
        record_kind="risk_event",
        fields=(
            "id",
            "risk_id",
            "event_type",
            "actor_type",
            "occurred_at",
            "actor_user_id",
            "previous_state_safe",
            "new_state_safe",
            "analysis_job_id",
            "evidence_refs",
            "reason_safe",
            "previous_event_hash",
            "event_hash",
        ),
    )
    return RiskEvent(
        id=str(data["id"]),
        risk_id=str(data["risk_id"]),
        event_type=RiskEventType(data["event_type"]),
        actor_type=ActorType(data["actor_type"]),
        occurred_at=_datetime(data["occurred_at"]),
        actor_user_id=_optional_str(data["actor_user_id"]),
        previous_state_safe=_mapping(data["previous_state_safe"]),
        new_state_safe=_mapping(data["new_state_safe"]),
        analysis_job_id=_optional_str(data["analysis_job_id"]),
        evidence_refs=tuple(str(item) for item in _list(data["evidence_refs"])),
        reason_safe=_optional_str(data["reason_safe"]),
        previous_event_hash=_optional_str(data["previous_event_hash"]),
        event_hash=_optional_str(data["event_hash"]),
    )


def audit_event_to_document(value: AuditEvent) -> Document:
    return _document(
        "audit_event",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        event_type=value.event_type,
        actor_type=value.actor_type,
        occurred_at=value.occurred_at,
        actor_user_id=value.actor_user_id,
        metadata_safe=value.metadata_safe,
    )


def audit_event_from_document(document: Mapping[str, object]) -> AuditEvent:
    data = _require_shape(
        document,
        record_kind="audit_event",
        fields=(
            "id",
            "risk_workspace_id",
            "event_type",
            "actor_type",
            "occurred_at",
            "actor_user_id",
            "metadata_safe",
        ),
    )
    return AuditEvent(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        event_type=AuditEventType(data["event_type"]),
        actor_type=ActorType(data["actor_type"]),
        occurred_at=_datetime(data["occurred_at"]),
        actor_user_id=_optional_str(data["actor_user_id"]),
        metadata_safe=_mapping(data["metadata_safe"]),
    )


def source_access_event_to_document(value: SourceAccessEvent) -> Document:
    return _document(
        "source_access_event",
        id=value.id,
        risk_workspace_id=value.risk_workspace_id,
        mount_id=value.mount_id,
        artifact_id=value.artifact_id,
        access_type=value.access_type,
        revision=value.revision,
        content_bytes=value.content_bytes,
        occurred_at=value.occurred_at,
        analysis_job_id=value.analysis_job_id,
        provider_request_id=value.provider_request_id,
    )


def source_access_event_from_document(document: Mapping[str, object]) -> SourceAccessEvent:
    data = _require_shape(
        document,
        record_kind="source_access_event",
        fields=(
            "id",
            "risk_workspace_id",
            "mount_id",
            "artifact_id",
            "access_type",
            "revision",
            "content_bytes",
            "occurred_at",
            "analysis_job_id",
            "provider_request_id",
        ),
    )
    return SourceAccessEvent(
        id=str(data["id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        mount_id=str(data["mount_id"]),
        artifact_id=str(data["artifact_id"]),
        access_type=SourceAccessType(data["access_type"]),
        revision=str(data["revision"]),
        content_bytes=_int(data["content_bytes"]),
        occurred_at=_datetime(data["occurred_at"]),
        analysis_job_id=_optional_str(data["analysis_job_id"]),
        provider_request_id=_optional_str(data["provider_request_id"]),
    )


def notification_to_document(value: Notification) -> Document:
    return _document(
        "notification",
        id=value.id,
        user_id=value.user_id,
        risk_workspace_id=value.risk_workspace_id,
        notification_type=value.notification_type,
        status=value.status,
        created_at=value.created_at,
        read_at=value.read_at,
        metadata_safe=value.metadata_safe,
    )


def notification_from_document(document: Mapping[str, object]) -> Notification:
    data = _require_shape(
        document,
        record_kind="notification",
        fields=(
            "id",
            "user_id",
            "risk_workspace_id",
            "notification_type",
            "status",
            "created_at",
            "read_at",
            "metadata_safe",
        ),
    )
    return Notification(
        id=str(data["id"]),
        user_id=str(data["user_id"]),
        risk_workspace_id=str(data["risk_workspace_id"]),
        notification_type=NotificationType(data["notification_type"]),
        status=NotificationStatus(data["status"]),
        created_at=_datetime(data["created_at"]),
        read_at=_optional_datetime(data["read_at"]),
        metadata_safe=_mapping(data["metadata_safe"]),
    )


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise DocumentMappingError(f"expected datetime, got {type(value).__name__}")
    return value


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DocumentMappingError(f"expected string or null, got {type(value).__name__}")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DocumentMappingError(f"expected mapping, got {type(value).__name__}")
    if any(not isinstance(key, str) for key in value):
        raise DocumentMappingError("document mapping keys must be strings")
    return value


def _list(value: object) -> list[object] | tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise DocumentMappingError(f"expected list, got {type(value).__name__}")
    return value


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentMappingError(f"expected integer, got {type(value).__name__}")
    return value


Encoder = Callable[[Any], Document]
Decoder = Callable[[Mapping[str, object]], Any]


__all__ = [name for name in globals() if name.endswith(("_to_document", "_from_document"))] + [
    "Document",
    "DocumentMappingError",
]
