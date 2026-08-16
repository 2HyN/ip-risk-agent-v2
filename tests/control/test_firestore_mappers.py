from __future__ import annotations

from datetime import datetime, timezone

import pytest

from iprisk_contracts import (
    AnalysisType,
    ChangeType,
    ReviewPriority,
    SourceAccessType,
    SourceType,
)
from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.process_change import ChangeEvent, ChangeEventStatus
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    Membership,
    MembershipInvitation,
    MembershipRole,
    MembershipStatus,
    invitation_id_for,
    membership_id_for,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
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
from ip_risk_agent.core.workspaces import RiskWorkspace
from ip_risk_agent.persistence.core_firestore.mappers import (
    DocumentMappingError,
    analysis_job_from_document,
    analysis_job_to_document,
    artifact_from_document,
    artifact_state_from_document,
    artifact_state_to_document,
    artifact_to_document,
    audit_event_from_document,
    audit_event_to_document,
    change_event_from_document,
    change_event_to_document,
    invitation_from_document,
    invitation_to_document,
    membership_from_document,
    membership_to_document,
    mount_from_document,
    mount_to_document,
    notification_from_document,
    notification_to_document,
    risk_event_from_document,
    risk_event_to_document,
    risk_evidence_from_document,
    risk_evidence_to_document,
    risk_from_document,
    risk_to_document,
    source_access_event_from_document,
    source_access_event_to_document,
    source_connection_from_document,
    source_connection_to_document,
    source_workspace_from_document,
    source_workspace_to_document,
    user_from_document,
    user_to_document,
    workspace_from_document,
    workspace_to_document,
)
from ip_risk_agent.persistence.core_firestore.schema import CANONICAL_COLLECTIONS

NOW = datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc)


def canonical_records():
    user = User("user-1", "subject-1", "user@example.com", "User", NOW, NOW)
    workspace = RiskWorkspace(
        "vws-1", "Workspace", "user-1", "security-v1", "retention-v1", NOW, NOW
    )
    membership = Membership(
        membership_id_for("vws-1", "user-1"),
        "vws-1",
        "user-1",
        MembershipRole.OWNER,
        MembershipStatus.ACTIVE,
        "user-1",
        NOW,
        NOW,
    )
    invitation = MembershipInvitation(
        invitation_id_for("vws-1", "viewer@example.com"),
        "vws-1",
        "viewer@example.com",
        MembershipRole.VIEWER,
        InvitationStatus.PENDING,
        "user-1",
        NOW,
        NOW,
    )
    connection = SourceConnection(
        "connection-1",
        SourceType.GITHUB,
        "user-1",
        SourceConnectionStatus.ACTIVE,
        NOW,
        NOW,
        provider_subject="installation-1",
        credential_ref="secret-ref-only",
    )
    source_workspace = SourceWorkspace(
        "source-1",
        "connection-1",
        SourceType.GITHUB,
        "repo-1",
        "org/repo",
        SourceWorkspaceStatus.ACTIVE,
        NOW,
        NOW,
        {"branch": "main", "paths": ["backend"]},
    )
    mount = WorkspaceMount(
        "mount-1",
        "vws-1",
        "source-1",
        "Backend",
        "user-1",
        "connection-1",
        MountStatus.ACTIVE,
        NOW,
        NOW,
    )
    artifact = Artifact(
        "artifact-1",
        "vws-1",
        "mount-1",
        "source-1",
        SourceType.GITHUB,
        "path:main.py",
        "main.py",
        "Backend/main.py",
        ArtifactStatus.ACTIVE,
        NOW,
        NOW,
        {"provider_locator": "safe-id"},
    )
    artifact_state = ArtifactState(
        "artifact-1",
        "revision-1",
        "checksum-1",
        ArtifactAvailability.AVAILABLE,
        NOW,
        {AnalysisType.PATENT: "revision-1"},
    )
    change_event = ChangeEvent(
        "change-1",
        "fingerprint-1",
        "vws-1",
        "mount-1",
        "source-1",
        "path:main.py",
        SourceType.GITHUB,
        ChangeType.UPDATE,
        "revision-1",
        None,
        NOW,
        ChangeEventStatus.PENDING,
        0,
        NOW,
        NOW,
        artifact_id="artifact-1",
        safe_metadata={"delivery": "webhook"},
    )
    job = AnalysisJob(
        "job-1",
        "change-1",
        "artifact-1",
        "revision-1",
        (AnalysisType.PATENT, AnalysisType.LICENSE),
        AnalysisJobStatus.QUEUED,
        NOW,
    )
    risk = Risk(
        "risk-1",
        "vws-1",
        "artifact-1",
        AnalysisType.PATENT,
        "risk-key-1",
        RiskLifecycleState.NEW,
        ReviewDisposition.UNREVIEWED,
        ReviewPriority.HIGH,
        "Potential overlap",
        NOW,
        NOW,
        "job-1",
        NOW,
    )
    evidence = RiskEvidence(
        "evidence-1",
        "risk-1",
        "job-1",
        "result-evidence-1",
        "TEXT",
        "minimal excerpt",
        "segment-1",
        "revision-1",
        NOW,
        {"page": 1},
    )
    risk_event = RiskEvent(
        "risk-event-1",
        "risk-1",
        RiskEventType.DETECTED,
        ActorType.SYSTEM,
        NOW,
        new_state_safe={"lifecycle_state": "NEW"},
        evidence_refs=("evidence-1",),
    )
    audit = AuditEvent(
        "audit-1",
        "vws-1",
        AuditEventType.WORKSPACE_CREATED,
        ActorType.USER,
        NOW,
        actor_user_id="user-1",
        metadata_safe={"workspace_name": "Workspace"},
    )
    access = SourceAccessEvent(
        "access-1",
        "vws-1",
        "mount-1",
        "artifact-1",
        SourceAccessType.DIFF,
        "revision-1",
        128,
        NOW,
        analysis_job_id="job-1",
    )
    notification = Notification(
        "notification-1",
        "user-1",
        "vws-1",
        NotificationType.RISK_HIGH_DETECTED,
        NotificationStatus.UNREAD,
        NOW,
        metadata_safe={"risk_id": "risk-1"},
    )
    return (
        (user, user_to_document, user_from_document),
        (workspace, workspace_to_document, workspace_from_document),
        (membership, membership_to_document, membership_from_document),
        (invitation, invitation_to_document, invitation_from_document),
        (connection, source_connection_to_document, source_connection_from_document),
        (source_workspace, source_workspace_to_document, source_workspace_from_document),
        (mount, mount_to_document, mount_from_document),
        (artifact, artifact_to_document, artifact_from_document),
        (artifact_state, artifact_state_to_document, artifact_state_from_document),
        (change_event, change_event_to_document, change_event_from_document),
        (job, analysis_job_to_document, analysis_job_from_document),
        (risk, risk_to_document, risk_from_document),
        (evidence, risk_evidence_to_document, risk_evidence_from_document),
        (risk_event, risk_event_to_document, risk_event_from_document),
        (audit, audit_event_to_document, audit_event_from_document),
        (access, source_access_event_to_document, source_access_event_from_document),
        (notification, notification_to_document, notification_from_document),
    )


@pytest.mark.parametrize(("value", "encoder", "decoder"), canonical_records())
def test_all_canonical_records_round_trip_strictly(value, encoder, decoder) -> None:
    document = encoder(value)
    assert document["schema_version"] == 1
    assert isinstance(document["record_kind"], str)
    assert decoder(document) == value


def test_mapper_rejects_unknown_fields_and_schema_versions() -> None:
    user, encoder, decoder = canonical_records()[0]
    document = encoder(user)
    with pytest.raises(DocumentMappingError, match="extra"):
        decoder({**document, "unexpected": "field"})
    with pytest.raises(DocumentMappingError, match="unsupported"):
        decoder({**document, "schema_version": 2})


def test_membership_discriminator_and_mount_alias_key_are_verified() -> None:
    membership, membership_encoder, _ = canonical_records()[2]
    invitation, invitation_encoder, _ = canonical_records()[3]
    mount, mount_encoder, mount_decoder = canonical_records()[6]
    assert membership_encoder(membership)["record_kind"] == "membership"
    assert invitation_encoder(invitation)["record_kind"] == "membership_invitation"
    mount_document = mount_encoder(mount)
    assert mount_document["alias_key"] == "backend"
    with pytest.raises(DocumentMappingError, match="alias_key"):
        mount_decoder({**mount_document, "alias_key": "wrong"})


def test_exactly_the_sixteen_specified_collections_are_declared() -> None:
    assert len(CANONICAL_COLLECTIONS) == 16
    assert len(set(CANONICAL_COLLECTIONS)) == 16
