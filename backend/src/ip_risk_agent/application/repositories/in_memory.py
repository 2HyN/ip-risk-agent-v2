"""Deterministic in-memory repositories for the control-plane application.

The implementation is intentionally transaction-oriented.  Each unit of work
operates on an isolated snapshot and publishes the snapshot only when the
store revision still matches the revision observed at transaction start.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from iprisk_contracts import AnalysisType

from ip_risk_agent.application.analysis_jobs.models import AnalysisJob
from ip_risk_agent.application.process_change.models import ChangeEvent
from ip_risk_agent.core.artifacts import Artifact, ArtifactState
from ip_risk_agent.core.audit import AuditEvent, SourceAccessEvent
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipInvitation,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.mounts import SourceConnection, SourceWorkspace, WorkspaceMount, mount_alias_key
from ip_risk_agent.core.notifications import Notification
from ip_risk_agent.core.risk import Risk, RiskEvidence, RiskEvent, RiskLifecycleState
from ip_risk_agent.core.workspaces import RiskWorkspace

from .errors import (
    ConcurrencyConflictError,
    RecordNotFoundError,
    TransactionClosedError,
    UniqueConstraintViolation,
)

T = TypeVar("T")


def _duplicate(kind: str, key: object) -> UniqueConstraintViolation:
    return UniqueConstraintViolation(f"{kind} already exists: {key!r}")


def _missing(kind: str, key: object) -> RecordNotFoundError:
    return RecordNotFoundError(f"{kind} was not found: {key!r}")


def _sorted(values: list[T], *, key: Callable[[T], object]) -> tuple[T, ...]:
    return tuple(sorted(values, key=key))


@dataclass(slots=True)
class _ControlState:
    users: dict[str, User] = field(default_factory=dict)
    users_by_google_subject: dict[str, str] = field(default_factory=dict)
    workspaces: dict[str, RiskWorkspace] = field(default_factory=dict)
    memberships: dict[str, Membership | MembershipInvitation] = field(default_factory=dict)
    source_connections: dict[str, SourceConnection] = field(default_factory=dict)
    source_workspaces: dict[str, SourceWorkspace] = field(default_factory=dict)
    mounts: dict[str, WorkspaceMount] = field(default_factory=dict)
    mounts_by_alias: dict[tuple[str, str], str] = field(default_factory=dict)
    mounts_by_source_workspace: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    artifacts_by_source_identity: dict[tuple[str, str], str] = field(default_factory=dict)
    artifact_states: dict[str, ArtifactState] = field(default_factory=dict)
    change_events: dict[str, ChangeEvent] = field(default_factory=dict)
    change_events_by_fingerprint: dict[str, str] = field(default_factory=dict)
    analysis_jobs: dict[str, AnalysisJob] = field(default_factory=dict)
    risks: dict[str, Risk] = field(default_factory=dict)
    risks_by_key: dict[str, str] = field(default_factory=dict)
    risk_evidence: dict[str, RiskEvidence] = field(default_factory=dict)
    risk_events: dict[str, RiskEvent] = field(default_factory=dict)
    audit_events: dict[str, AuditEvent] = field(default_factory=dict)
    source_access_events: dict[str, SourceAccessEvent] = field(default_factory=dict)
    notifications: dict[str, Notification] = field(default_factory=dict)

    def clone(self) -> _ControlState:
        return _ControlState(
            users=dict(self.users),
            users_by_google_subject=dict(self.users_by_google_subject),
            workspaces=dict(self.workspaces),
            memberships=dict(self.memberships),
            source_connections=dict(self.source_connections),
            source_workspaces=dict(self.source_workspaces),
            mounts=dict(self.mounts),
            mounts_by_alias=dict(self.mounts_by_alias),
            mounts_by_source_workspace=dict(self.mounts_by_source_workspace),
            artifacts=dict(self.artifacts),
            artifacts_by_source_identity=dict(self.artifacts_by_source_identity),
            artifact_states=dict(self.artifact_states),
            change_events=dict(self.change_events),
            change_events_by_fingerprint=dict(self.change_events_by_fingerprint),
            analysis_jobs=dict(self.analysis_jobs),
            risks=dict(self.risks),
            risks_by_key=dict(self.risks_by_key),
            risk_evidence=dict(self.risk_evidence),
            risk_events=dict(self.risk_events),
            audit_events=dict(self.audit_events),
            source_access_events=dict(self.source_access_events),
            notifications=dict(self.notifications),
        )


class _Repository:
    def __init__(self, state: _ControlState, ensure_open: Callable[[], None]) -> None:
        self._state = state
        self._ensure_open = ensure_open

    def _open(self) -> None:
        self._ensure_open()


class InMemoryUserRepository(_Repository):
    async def get(self, user_id: str) -> User | None:
        self._open()
        return self._state.users.get(user_id)

    async def get_by_google_subject(self, google_subject: str) -> User | None:
        self._open()
        user_id = self._state.users_by_google_subject.get(google_subject)
        return self._state.users.get(user_id) if user_id is not None else None

    async def add(self, user: User) -> None:
        self._open()
        if user.id in self._state.users:
            raise _duplicate("user id", user.id)
        if user.google_subject in self._state.users_by_google_subject:
            raise _duplicate("Google subject", user.google_subject)
        self._state.users[user.id] = user
        self._state.users_by_google_subject[user.google_subject] = user.id

    async def save(self, user: User) -> None:
        self._open()
        previous = self._state.users.get(user.id)
        if previous is None:
            raise _missing("user", user.id)
        if previous.google_subject != user.google_subject:
            raise UniqueConstraintViolation("Google subject is immutable")
        subject_owner = self._state.users_by_google_subject.get(user.google_subject)
        if subject_owner not in (None, user.id):
            raise _duplicate("Google subject", user.google_subject)
        self._state.users[user.id] = user
        self._state.users_by_google_subject[user.google_subject] = user.id


class InMemoryWorkspaceRepository(_Repository):
    async def get(self, workspace_id: str) -> RiskWorkspace | None:
        self._open()
        return self._state.workspaces.get(workspace_id)

    async def add(self, workspace: RiskWorkspace) -> None:
        self._open()
        if workspace.id in self._state.workspaces:
            raise _duplicate("workspace", workspace.id)
        self._state.workspaces[workspace.id] = workspace

    async def save(self, workspace: RiskWorkspace) -> None:
        self._open()
        if workspace.id not in self._state.workspaces:
            raise _missing("workspace", workspace.id)
        self._state.workspaces[workspace.id] = workspace

    async def list_for_user(self, user_id: str) -> tuple[RiskWorkspace, ...]:
        self._open()
        workspace_ids = {
            record.risk_workspace_id
            for record in self._state.memberships.values()
            if isinstance(record, Membership)
            and record.user_id == user_id
            and record.status is MembershipStatus.ACTIVE
        }
        return _sorted(
            [workspace for key, workspace in self._state.workspaces.items() if key in workspace_ids],
            key=lambda workspace: workspace.id,
        )


class InMemoryMembershipRepository(_Repository):
    async def get(self, risk_workspace_id: str, user_id: str) -> Membership | None:
        self._open()
        record = self._state.memberships.get(membership_id_for(risk_workspace_id, user_id))
        return record if isinstance(record, Membership) else None

    async def get_invitation(self, invitation_id: str) -> MembershipInvitation | None:
        self._open()
        record = self._state.memberships.get(invitation_id)
        return record if isinstance(record, MembershipInvitation) else None

    async def add(self, membership: Membership) -> None:
        self._open()
        if membership.id in self._state.memberships:
            raise _duplicate("membership record", membership.id)
        self._state.memberships[membership.id] = membership

    async def save(self, membership: Membership) -> None:
        self._open()
        previous = self._state.memberships.get(membership.id)
        if not isinstance(previous, Membership):
            raise _missing("membership", membership.id)
        if (
            previous.risk_workspace_id != membership.risk_workspace_id
            or previous.user_id != membership.user_id
        ):
            raise UniqueConstraintViolation("membership identity fields are immutable")
        self._state.memberships[membership.id] = membership

    async def add_invitation(self, invitation: MembershipInvitation) -> None:
        self._open()
        if invitation.id in self._state.memberships:
            raise _duplicate("membership record", invitation.id)
        self._state.memberships[invitation.id] = invitation

    async def save_invitation(self, invitation: MembershipInvitation) -> None:
        self._open()
        previous = self._state.memberships.get(invitation.id)
        if not isinstance(previous, MembershipInvitation):
            raise _missing("membership invitation", invitation.id)
        if (
            previous.risk_workspace_id != invitation.risk_workspace_id
            or previous.email != invitation.email
        ):
            raise UniqueConstraintViolation("membership invitation identity fields are immutable")
        self._state.memberships[invitation.id] = invitation

    async def list_members(self, risk_workspace_id: str) -> tuple[Membership, ...]:
        self._open()
        return _sorted(
            [
                record
                for record in self._state.memberships.values()
                if isinstance(record, Membership)
                and record.risk_workspace_id == risk_workspace_id
            ],
            key=lambda membership: membership.id,
        )

    async def list_invitations(self, risk_workspace_id: str) -> tuple[MembershipInvitation, ...]:
        self._open()
        return _sorted(
            [
                record
                for record in self._state.memberships.values()
                if isinstance(record, MembershipInvitation)
                and record.risk_workspace_id == risk_workspace_id
            ],
            key=lambda invitation: invitation.id,
        )


class InMemorySourceMetadataRepository(_Repository):
    async def get_connection(self, connection_id: str) -> SourceConnection | None:
        self._open()
        return self._state.source_connections.get(connection_id)

    async def add_connection(self, connection: SourceConnection) -> None:
        self._open()
        if connection.id in self._state.source_connections:
            raise _duplicate("source connection", connection.id)
        self._state.source_connections[connection.id] = connection

    async def save_connection(self, connection: SourceConnection) -> None:
        self._open()
        if connection.id not in self._state.source_connections:
            raise _missing("source connection", connection.id)
        self._state.source_connections[connection.id] = connection

    async def get_source_workspace(self, source_workspace_id: str) -> SourceWorkspace | None:
        self._open()
        return self._state.source_workspaces.get(source_workspace_id)

    async def add_source_workspace(self, source_workspace: SourceWorkspace) -> None:
        self._open()
        if source_workspace.id in self._state.source_workspaces:
            raise _duplicate("source workspace", source_workspace.id)
        self._state.source_workspaces[source_workspace.id] = source_workspace

    async def save_source_workspace(self, source_workspace: SourceWorkspace) -> None:
        self._open()
        if source_workspace.id not in self._state.source_workspaces:
            raise _missing("source workspace", source_workspace.id)
        self._state.source_workspaces[source_workspace.id] = source_workspace


class InMemoryMountRepository(_Repository):
    async def get(self, mount_id: str) -> WorkspaceMount | None:
        self._open()
        return self._state.mounts.get(mount_id)

    async def add(self, mount: WorkspaceMount) -> None:
        self._open()
        alias_key = (mount.risk_workspace_id, mount_alias_key(mount.alias))
        if mount.id in self._state.mounts:
            raise _duplicate("mount", mount.id)
        if alias_key in self._state.mounts_by_alias:
            raise _duplicate("workspace mount alias", alias_key)
        if mount.source_workspace_id in self._state.mounts_by_source_workspace:
            raise _duplicate("source workspace mount", mount.source_workspace_id)
        self._state.mounts[mount.id] = mount
        self._state.mounts_by_alias[alias_key] = mount.id
        self._state.mounts_by_source_workspace[mount.source_workspace_id] = mount.id

    async def save(self, mount: WorkspaceMount) -> None:
        self._open()
        previous = self._state.mounts.get(mount.id)
        if previous is None:
            raise _missing("mount", mount.id)
        if previous.risk_workspace_id != mount.risk_workspace_id:
            raise UniqueConstraintViolation("a mount cannot move between virtual workspaces")
        if previous.source_workspace_id != mount.source_workspace_id:
            raise UniqueConstraintViolation("a mount cannot change its source workspace")
        previous_alias = (previous.risk_workspace_id, mount_alias_key(previous.alias))
        alias_key = (mount.risk_workspace_id, mount_alias_key(mount.alias))
        alias_owner = self._state.mounts_by_alias.get(alias_key)
        if alias_owner not in (None, mount.id):
            raise _duplicate("workspace mount alias", alias_key)
        if previous_alias != alias_key:
            self._state.mounts_by_alias.pop(previous_alias, None)
        self._state.mounts[mount.id] = mount
        self._state.mounts_by_alias[alias_key] = mount.id

    async def remove(self, mount_id: str) -> None:
        self._open()
        mount = self._state.mounts.pop(mount_id, None)
        if mount is None:
            raise _missing("mount", mount_id)
        self._state.mounts_by_alias.pop(
            (mount.risk_workspace_id, mount_alias_key(mount.alias)), None
        )
        self._state.mounts_by_source_workspace.pop(mount.source_workspace_id, None)

    async def list_for_workspace(self, risk_workspace_id: str) -> tuple[WorkspaceMount, ...]:
        self._open()
        return _sorted(
            [mount for mount in self._state.mounts.values() if mount.risk_workspace_id == risk_workspace_id],
            key=lambda mount: mount.id,
        )

    async def list_by_custodian(
        self, risk_workspace_id: str, user_id: str
    ) -> tuple[WorkspaceMount, ...]:
        self._open()
        return _sorted(
            [
                mount
                for mount in self._state.mounts.values()
                if mount.risk_workspace_id == risk_workspace_id
                and mount.mounted_by_user_id == user_id
            ],
            key=lambda mount: mount.id,
        )


class InMemoryArtifactRepository(_Repository):
    async def get(self, artifact_id: str) -> Artifact | None:
        self._open()
        return self._state.artifacts.get(artifact_id)

    async def get_by_source_identity(self, source_workspace_id: str, source_artifact_id: str) -> Artifact | None:
        self._open()
        artifact_id = self._state.artifacts_by_source_identity.get(
            (source_workspace_id, source_artifact_id)
        )
        return self._state.artifacts.get(artifact_id) if artifact_id is not None else None

    async def add(self, artifact: Artifact, state: ArtifactState) -> None:
        self._open()
        source_key = (artifact.source_workspace_id, artifact.source_artifact_id)
        if artifact.id in self._state.artifacts:
            raise _duplicate("artifact", artifact.id)
        if source_key in self._state.artifacts_by_source_identity:
            raise _duplicate("source artifact identity", source_key)
        if state.artifact_id != artifact.id:
            raise UniqueConstraintViolation("artifact state must belong to the added artifact")
        if state.artifact_id in self._state.artifact_states:
            raise _duplicate("artifact state", state.artifact_id)
        self._state.artifacts[artifact.id] = artifact
        self._state.artifacts_by_source_identity[source_key] = artifact.id
        self._state.artifact_states[state.artifact_id] = state

    async def save(self, artifact: Artifact) -> None:
        self._open()
        previous = self._state.artifacts.get(artifact.id)
        if previous is None:
            raise _missing("artifact", artifact.id)
        if previous.source_workspace_id != artifact.source_workspace_id:
            raise UniqueConstraintViolation("an artifact cannot move between source workspaces")
        previous_key = (previous.source_workspace_id, previous.source_artifact_id)
        source_key = (artifact.source_workspace_id, artifact.source_artifact_id)
        source_owner = self._state.artifacts_by_source_identity.get(source_key)
        if source_owner not in (None, artifact.id):
            raise _duplicate("source artifact identity", source_key)
        if previous_key != source_key:
            self._state.artifacts_by_source_identity.pop(previous_key, None)
        self._state.artifacts[artifact.id] = artifact
        self._state.artifacts_by_source_identity[source_key] = artifact.id

    async def get_state(self, artifact_id: str) -> ArtifactState | None:
        self._open()
        return self._state.artifact_states.get(artifact_id)

    async def save_state(self, state: ArtifactState) -> None:
        self._open()
        if state.artifact_id not in self._state.artifacts:
            raise _missing("artifact", state.artifact_id)
        if state.artifact_id not in self._state.artifact_states:
            raise _missing("artifact state", state.artifact_id)
        self._state.artifact_states[state.artifact_id] = state


class InMemoryChangeEventRepository(_Repository):
    async def get(self, change_event_id: str) -> ChangeEvent | None:
        self._open()
        return self._state.change_events.get(change_event_id)

    async def get_by_fingerprint(self, fingerprint: str) -> ChangeEvent | None:
        self._open()
        event_id = self._state.change_events_by_fingerprint.get(fingerprint)
        return self._state.change_events.get(event_id) if event_id is not None else None

    async def add(self, change_event: ChangeEvent) -> None:
        self._open()
        if change_event.id in self._state.change_events:
            raise _duplicate("change event", change_event.id)
        if change_event.event_fingerprint in self._state.change_events_by_fingerprint:
            raise _duplicate("change-event fingerprint", change_event.event_fingerprint)
        self._state.change_events[change_event.id] = change_event
        self._state.change_events_by_fingerprint[change_event.event_fingerprint] = change_event.id

    async def save(self, change_event: ChangeEvent) -> None:
        self._open()
        previous = self._state.change_events.get(change_event.id)
        if previous is None:
            raise _missing("change event", change_event.id)
        if previous.event_fingerprint != change_event.event_fingerprint:
            raise UniqueConstraintViolation("change-event fingerprint is immutable")
        fingerprint_owner = self._state.change_events_by_fingerprint.get(
            change_event.event_fingerprint
        )
        if fingerprint_owner not in (None, change_event.id):
            raise _duplicate("change-event fingerprint", change_event.event_fingerprint)
        self._state.change_events[change_event.id] = change_event
        self._state.change_events_by_fingerprint[change_event.event_fingerprint] = change_event.id


class InMemoryAnalysisJobRepository(_Repository):
    async def get(self, job_id: str) -> AnalysisJob | None:
        self._open()
        return self._state.analysis_jobs.get(job_id)

    async def add(self, job: AnalysisJob) -> None:
        self._open()
        if job.id in self._state.analysis_jobs:
            raise _duplicate("analysis job", job.id)
        self._state.analysis_jobs[job.id] = job

    async def save(self, job: AnalysisJob) -> None:
        self._open()
        previous = self._state.analysis_jobs.get(job.id)
        if previous is None:
            raise _missing("analysis job", job.id)
        if (
            previous.change_event_id != job.change_event_id
            or previous.artifact_id != job.artifact_id
            or previous.revision != job.revision
        ):
            raise UniqueConstraintViolation("analysis job source identity is immutable")
        if not set(job.requested_analysis_types).issubset(
            previous.requested_analysis_types
        ):
            raise UniqueConstraintViolation(
                "analysis job requested types may only be narrowed"
            )
        self._state.analysis_jobs[job.id] = job

    async def list_for_change(self, change_event_id: str) -> tuple[AnalysisJob, ...]:
        self._open()
        return _sorted(
            [job for job in self._state.analysis_jobs.values() if job.change_event_id == change_event_id],
            key=lambda job: job.id,
        )


class InMemoryRiskRepository(_Repository):
    async def get(self, risk_id: str) -> Risk | None:
        self._open()
        return self._state.risks.get(risk_id)

    async def get_by_key(self, risk_key: str) -> Risk | None:
        self._open()
        risk_id = self._state.risks_by_key.get(risk_key)
        return self._state.risks.get(risk_id) if risk_id is not None else None

    async def add(self, risk: Risk) -> None:
        self._open()
        if risk.id in self._state.risks:
            raise _duplicate("risk", risk.id)
        if risk.risk_key in self._state.risks_by_key:
            raise _duplicate("risk key", risk.risk_key)
        self._state.risks[risk.id] = risk
        self._state.risks_by_key[risk.risk_key] = risk.id

    async def save(self, risk: Risk) -> None:
        self._open()
        previous = self._state.risks.get(risk.id)
        if previous is None:
            raise _missing("risk", risk.id)
        if previous.risk_key != risk.risk_key:
            raise UniqueConstraintViolation("risk key is immutable")
        risk_key_owner = self._state.risks_by_key.get(risk.risk_key)
        if risk_key_owner not in (None, risk.id):
            raise _duplicate("risk key", risk.risk_key)
        self._state.risks[risk.id] = risk
        self._state.risks_by_key[risk.risk_key] = risk.id

    async def list_for_artifact(
        self,
        artifact_id: str,
        analysis_type: AnalysisType,
        lifecycle_states: frozenset[RiskLifecycleState] | None = None,
    ) -> tuple[Risk, ...]:
        self._open()
        return _sorted(
            [
                risk
                for risk in self._state.risks.values()
                if risk.artifact_id == artifact_id
                and risk.analysis_type is analysis_type
                and (lifecycle_states is None or risk.lifecycle_state in lifecycle_states)
            ],
            key=lambda risk: risk.id,
        )

    async def add_evidence(self, evidence: RiskEvidence) -> None:
        self._open()
        if evidence.id in self._state.risk_evidence:
            raise _duplicate("risk evidence", evidence.id)
        if evidence.risk_id not in self._state.risks:
            raise _missing("risk", evidence.risk_id)
        self._state.risk_evidence[evidence.id] = evidence

    async def list_evidence(self, risk_id: str) -> tuple[RiskEvidence, ...]:
        self._open()
        return _sorted(
            [evidence for evidence in self._state.risk_evidence.values() if evidence.risk_id == risk_id],
            key=lambda evidence: evidence.id,
        )

    async def append_event(self, event: RiskEvent) -> None:
        self._open()
        if event.id in self._state.risk_events:
            raise _duplicate("risk event", event.id)
        if event.risk_id not in self._state.risks:
            raise _missing("risk", event.risk_id)
        self._state.risk_events[event.id] = event

    async def list_events(self, risk_id: str) -> tuple[RiskEvent, ...]:
        self._open()
        return _sorted(
            [event for event in self._state.risk_events.values() if event.risk_id == risk_id],
            key=lambda event: (event.occurred_at, event.id),
        )


class InMemoryAuditRepository(_Repository):
    async def append(self, event: AuditEvent) -> None:
        self._open()
        if event.id in self._state.audit_events:
            raise _duplicate("audit event", event.id)
        self._state.audit_events[event.id] = event

    async def list_for_workspace(self, risk_workspace_id: str) -> tuple[AuditEvent, ...]:
        self._open()
        return _sorted(
            [
                event
                for event in self._state.audit_events.values()
                if event.risk_workspace_id == risk_workspace_id
            ],
            key=lambda event: (event.occurred_at, event.id),
        )

    async def append_source_access(self, event: SourceAccessEvent) -> None:
        self._open()
        if event.id in self._state.source_access_events:
            raise _duplicate("source access event", event.id)
        self._state.source_access_events[event.id] = event

    async def get_source_access(self, event_id: str) -> SourceAccessEvent | None:
        self._open()
        return self._state.source_access_events.get(event_id)

    async def list_source_access(
        self, risk_workspace_id: str
    ) -> tuple[SourceAccessEvent, ...]:
        self._open()
        return _sorted(
            [
                event
                for event in self._state.source_access_events.values()
                if event.risk_workspace_id == risk_workspace_id
            ],
            key=lambda event: (event.occurred_at, event.id),
        )


class InMemoryNotificationRepository(_Repository):
    async def get(self, notification_id: str) -> Notification | None:
        self._open()
        return self._state.notifications.get(notification_id)

    async def add(self, notification: Notification) -> None:
        self._open()
        if notification.id in self._state.notifications:
            raise _duplicate("notification", notification.id)
        self._state.notifications[notification.id] = notification

    async def save(self, notification: Notification) -> None:
        self._open()
        if notification.id not in self._state.notifications:
            raise _missing("notification", notification.id)
        self._state.notifications[notification.id] = notification

    async def list_for_user(self, user_id: str) -> tuple[Notification, ...]:
        self._open()
        return _sorted(
            [item for item in self._state.notifications.values() if item.user_id == user_id],
            key=lambda item: (item.created_at, item.id),
        )


class InMemoryControlUnitOfWork:
    """Isolated snapshot transaction with store-level optimistic concurrency."""

    def __init__(self, store: InMemoryControlStore) -> None:
        self._store = store
        self._state: _ControlState | None = None
        self._base_revision: int | None = None
        self._closed = True

    async def __aenter__(self) -> InMemoryControlUnitOfWork:
        if not self._closed:
            raise TransactionClosedError("unit of work is already active")
        async with self._store._lock:
            self._state = self._store._state.clone()
            self._base_revision = self._store._revision
        self._closed = False
        self.users = InMemoryUserRepository(self._state, self._ensure_open)
        self.workspaces = InMemoryWorkspaceRepository(self._state, self._ensure_open)
        self.memberships = InMemoryMembershipRepository(self._state, self._ensure_open)
        self.source_metadata = InMemorySourceMetadataRepository(self._state, self._ensure_open)
        self.mounts = InMemoryMountRepository(self._state, self._ensure_open)
        self.artifacts = InMemoryArtifactRepository(self._state, self._ensure_open)
        self.change_events = InMemoryChangeEventRepository(self._state, self._ensure_open)
        self.analysis_jobs = InMemoryAnalysisJobRepository(self._state, self._ensure_open)
        self.risks = InMemoryRiskRepository(self._state, self._ensure_open)
        self.audit = InMemoryAuditRepository(self._state, self._ensure_open)
        self.notifications = InMemoryNotificationRepository(self._state, self._ensure_open)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._closed:
            await self.rollback()

    def _ensure_open(self) -> None:
        if self._closed or self._state is None or self._base_revision is None:
            raise TransactionClosedError("unit of work is not active")

    async def commit(self) -> None:
        self._ensure_open()
        assert self._state is not None
        assert self._base_revision is not None
        async with self._store._lock:
            if self._store._revision != self._base_revision:
                raise ConcurrencyConflictError(
                    "control store changed after this transaction started"
                )
            self._store._state = self._state.clone()
            self._store._revision += 1
        self._closed = True

    async def rollback(self) -> None:
        self._ensure_open()
        self._closed = True


class InMemoryControlStore:
    """Process-local store and callable unit-of-work factory."""

    def __init__(self) -> None:
        self._state = _ControlState()
        self._revision = 0
        self._lock = asyncio.Lock()

    def __call__(self) -> InMemoryControlUnitOfWork:
        return InMemoryControlUnitOfWork(self)

    @property
    def revision(self) -> int:
        return self._revision


__all__ = [
    "InMemoryControlStore",
    "InMemoryControlUnitOfWork",
]
