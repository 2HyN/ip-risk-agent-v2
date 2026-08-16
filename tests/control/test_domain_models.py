from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts import AnalysisType, ChangeType, SourceAccessType, SourceType
from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.process_change import ChangeEvent, ChangeEventStatus
from ip_risk_agent.core.artifacts import Artifact, ArtifactStatus
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import DomainInvariantError
from ip_risk_agent.core.memberships import MembershipRole, Permission, permissions_for
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
    mount_alias_key,
    normalize_mount_alias,
)
from ip_risk_agent.core.notifications import (
    Notification,
    NotificationStatus,
    NotificationType,
)
from ip_risk_agent.core.risk import (
    ActorType,
    ReviewDisposition,
    ReviewPriority,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskLifecycleState,
)

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


def test_user_requires_google_subject_and_aware_timestamps() -> None:
    with pytest.raises(DomainInvariantError, match="google_subject"):
        User("u1", " ", "user@example.com", "User", NOW, NOW)

    with pytest.raises(DomainInvariantError, match="timezone-aware"):
        User(
            "u1",
            "google-subject",
            "user@example.com",
            "User",
            datetime(2026, 8, 16, 9, 0),
            NOW,
        )


def test_role_permissions_are_monotonic_and_exclude_raw_source_authority() -> None:
    viewer = permissions_for(MembershipRole.VIEWER)
    reviewer = permissions_for(MembershipRole.RISK_REVIEWER)
    manager = permissions_for(MembershipRole.SOURCE_MANAGER)
    owner = permissions_for(MembershipRole.OWNER)

    assert viewer < reviewer < manager < owner
    assert Permission.RISK_REVIEW in reviewer
    assert Permission.OWN_SOURCE_MANAGE in manager
    assert owner == frozenset(Permission)
    assert all("RAW" not in permission.value for permission in Permission)


@pytest.mark.parametrize("alias", ["", "/", "../backend", "backend/secrets", "a\\b", "a//b"])
def test_mount_alias_rejects_ambiguous_paths(alias: str) -> None:
    with pytest.raises(DomainInvariantError):
        normalize_mount_alias(alias)


def test_mount_alias_is_presentation_only_and_has_casefolded_unique_key() -> None:
    mount = WorkspaceMount(
        id="mount-1",
        risk_workspace_id="vws-1",
        source_workspace_id="source-workspace-1",
        alias="/Backend/",
        mounted_by_user_id="user-1",
        source_connection_id="connection-1",
        status=MountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )

    assert mount.alias == "Backend"
    assert mount_alias_key("Backend") == mount_alias_key("backend")


def test_artifact_rejects_last_seen_before_first_seen() -> None:
    with pytest.raises(DomainInvariantError, match="last_seen_at"):
        Artifact(
            id="artifact-1",
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            source_workspace_id="source-workspace-1",
            source_type=SourceType.GITHUB,
            source_artifact_id="repo:path",
            display_name="file.py",
            logical_path="/backend/file.py",
            status=ArtifactStatus.ACTIVE,
            first_seen_at=NOW,
            last_seen_at=NOW - timedelta(seconds=1),
        )


def test_change_event_rejects_negative_attempts() -> None:
    with pytest.raises(DomainInvariantError, match="attempts"):
        ChangeEvent(
            id="change-1",
            event_fingerprint="fingerprint",
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            source_workspace_id="source-workspace-1",
            source_artifact_id="repo:path",
            source_type=SourceType.GITHUB,
            change_type=ChangeType.UPDATE,
            revision="abc",
            previous_revision=None,
            observed_at=NOW,
            status=ChangeEventStatus.PENDING,
            attempts=-1,
            created_at=NOW,
            updated_at=NOW,
        )


def test_analysis_job_requires_unique_nonempty_analysis_types() -> None:
    with pytest.raises(DomainInvariantError, match="must be unique"):
        AnalysisJob(
            id="job-1",
            change_event_id="change-1",
            artifact_id="artifact-1",
            revision="abc",
            requested_analysis_types=(AnalysisType.PATENT, AnalysisType.PATENT),
            status=AnalysisJobStatus.QUEUED,
            created_at=NOW,
        )


def test_resolved_risk_requires_resolved_at_and_active_risk_forbids_it() -> None:
    common = dict(
        id="risk-1",
        risk_workspace_id="vws-1",
        artifact_id="artifact-1",
        analysis_type=AnalysisType.PATENT,
        risk_key="risk-key",
        review_disposition=ReviewDisposition.UNREVIEWED,
        review_priority=ReviewPriority.HIGH,
        summary="Potential patent overlap",
        first_seen_at=NOW,
        last_seen_at=NOW,
        latest_analysis_job_id="job-1",
        updated_at=NOW,
    )

    with pytest.raises(ValueError, match="required"):
        Risk(lifecycle_state=RiskLifecycleState.RESOLVED, **common)
    with pytest.raises(ValueError, match="cannot have"):
        Risk(lifecycle_state=RiskLifecycleState.NEW, resolved_at=NOW, **common)


def test_user_authored_risk_event_requires_actor_user_id() -> None:
    with pytest.raises(ValueError, match="actor_user_id"):
        RiskEvent(
            id="event-1",
            risk_id="risk-1",
            event_type=RiskEventType.REVIEW_DISPOSITION_CHANGED,
            actor_type=ActorType.USER,
            occurred_at=NOW,
        )


def test_source_access_event_rejects_negative_content_size() -> None:
    with pytest.raises(DomainInvariantError, match="content_bytes"):
        SourceAccessEvent(
            id="access-1",
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            artifact_id="artifact-1",
            access_type=SourceAccessType.DIFF,
            revision="abc",
            content_bytes=-1,
            occurred_at=NOW,
        )


def test_system_audit_event_does_not_require_a_user_actor() -> None:
    event = AuditEvent(
        id="audit-1",
        risk_workspace_id="vws-1",
        event_type=AuditEventType.ANALYSIS_FAILED,
        actor_type=ActorType.SYSTEM,
        occurred_at=NOW,
    )
    assert event.actor_user_id is None


def test_notification_read_state_and_timestamp_must_agree() -> None:
    with pytest.raises(ValueError, match="requires read_at"):
        Notification(
            id="notification-1",
            user_id="user-1",
            risk_workspace_id="vws-1",
            notification_type=NotificationType.ANALYSIS_FAILED,
            status=NotificationStatus.READ,
            created_at=NOW,
        )


def test_safe_metadata_is_json_validated_and_recursively_immutable() -> None:
    source_workspace = SourceWorkspace(
        id="source-workspace-1",
        source_connection_id="connection-1",
        source_type=SourceType.GITHUB,
        external_scope_id="repository-1",
        display_name="company/backend",
        status=SourceWorkspaceStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        tracking_config_safe={"paths": ["src/**", {"excluded": False}]},
    )

    assert source_workspace.tracking_config_safe["paths"] == (
        "src/**",
        {"excluded": False},
    )
    with pytest.raises(TypeError):
        source_workspace.tracking_config_safe["new"] = "value"  # type: ignore[index]

    with pytest.raises(DomainInvariantError, match="JSON-safe"):
        SourceWorkspace(
            id="source-workspace-2",
            source_connection_id="connection-1",
            source_type=SourceType.GITHUB,
            external_scope_id="repository-2",
            display_name="company/unsafe",
            status=SourceWorkspaceStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            tracking_config_safe={"unsafe": object()},
        )
