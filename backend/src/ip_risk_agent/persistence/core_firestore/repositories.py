"""Firestore-backed implementations of the Control repository protocols."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from iprisk_contracts import AnalysisType
from ip_risk_agent.application.analysis_jobs.models import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.process_change.models import ChangeEvent
from ip_risk_agent.application.repositories import (
    RecordNotFoundError,
    TransactionClosedError,
    UniqueConstraintViolation,
)
from ip_risk_agent.core.artifacts import Artifact, ArtifactState
from ip_risk_agent.core.audit import AuditEvent, SourceAccessEvent
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipInvitation,
    MembershipStatus,
    membership_id_for,
    normalize_invitation_email,
)
from ip_risk_agent.core.mounts import (
    SourceConnection,
    SourceWorkspace,
    WorkspaceMount,
    mount_alias_key,
)
from ip_risk_agent.core.notifications import Notification, NotificationStatus
from ip_risk_agent.core.risk import Risk, RiskEvent, RiskEvidence, RiskLifecycleState
from ip_risk_agent.core.workspaces import RiskWorkspace

from .backend import (
    FirestoreDocumentBackend,
    GoogleFirestoreBackend,
    QueryFilter,
    StoredDocument,
)
from .mappers import (
    Decoder,
    DocumentMappingError,
    Encoder,
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
from .schema import (
    ANALYSIS_JOBS,
    ARTIFACTS,
    ARTIFACT_STATES,
    AUDIT_EVENTS,
    CHANGE_EVENTS,
    MEMBERSHIPS,
    NOTIFICATIONS,
    RISKS,
    RISK_EVIDENCE,
    RISK_EVENTS,
    RISK_WORKSPACES,
    SOURCE_ACCESS_EVENTS,
    SOURCE_CONNECTIONS,
    SOURCE_WORKSPACES,
    USERS,
    WORKSPACE_MOUNTS,
)
from .session import FirestoreDocumentSession
from .unique_keys import claim_unique_key, release_unique_key, resolve_unique_key

class _Repository:
    def __init__(self, session: FirestoreDocumentSession) -> None:
        self._session = session

    async def _get(
        self,
        collection: str,
        document_id: str,
        decoder: Decoder,
        *,
        identity_field: str = "id",
    ):
        document = await self._session.get(collection, document_id)
        if document is None:
            return None
        value = decoder(document)
        if getattr(value, identity_field) != document_id:
            raise DocumentMappingError(
                f"document path identity does not match {identity_field}: "
                f"{collection}/{document_id}"
            )
        return value

    async def _query(
        self,
        collection: str,
        filters: tuple[QueryFilter, ...],
        decoder: Decoder,
        *,
        identity_field: str = "id",
        sort_key: Callable[[Any], object] = lambda value: value.id,
    ) -> tuple:
        documents = await self._session.query(collection, filters)
        values = tuple(
            _decode_stored(item, decoder, identity_field=identity_field) for item in documents
        )
        return tuple(sorted(values, key=sort_key))

    async def _add(
        self, collection: str, document_id: str, value: object, encoder: Encoder
    ) -> None:
        await self._session.create(collection, document_id, encoder(value))

    async def _save(
        self, collection: str, document_id: str, value: object, encoder: Encoder
    ) -> None:
        await self._session.set(collection, document_id, encoder(value))


class FirestoreUserRepository(_Repository):
    async def get(self, user_id: str) -> User | None:
        return await self._get(USERS, user_id, user_from_document)

    async def get_by_google_subject(self, google_subject: str) -> User | None:
        owner = await resolve_unique_key(
            self._session,
            collection=USERS,
            namespace="google-subject",
            components=(google_subject,),
        )
        if owner is None:
            return None
        value = await self.get(owner)
        if value is None:
            raise DocumentMappingError("Google-subject sentinel points to a missing user")
        return value

    async def add(self, user: User) -> None:
        await claim_unique_key(
            self._session,
            collection=USERS,
            namespace="google-subject",
            components=(user.google_subject,),
            owner_document_id=user.id,
        )
        await self._add(USERS, user.id, user, user_to_document)

    async def save(self, user: User) -> None:
        previous = await _required(self.get(user.id), "user", user.id)
        if previous.google_subject != user.google_subject:
            raise UniqueConstraintViolation("Google subject is immutable")
        if user.session_version not in {
            previous.session_version,
            previous.session_version + 1,
        }:
            raise UniqueConstraintViolation(
                "user session version may only remain stable or increment once"
            )
        await claim_unique_key(
            self._session,
            collection=USERS,
            namespace="google-subject",
            components=(user.google_subject,),
            owner_document_id=user.id,
        )
        await self._save(USERS, user.id, user, user_to_document)


class FirestoreWorkspaceRepository(_Repository):
    async def get(self, workspace_id: str) -> RiskWorkspace | None:
        return await self._get(RISK_WORKSPACES, workspace_id, workspace_from_document)

    async def add(self, workspace: RiskWorkspace) -> None:
        await self._add(RISK_WORKSPACES, workspace.id, workspace, workspace_to_document)

    async def save(self, workspace: RiskWorkspace) -> None:
        previous = await _required(self.get(workspace.id), "workspace", workspace.id)
        if (
            previous.created_at != workspace.created_at
            or (
                previous.global_ignore_text != workspace.global_ignore_text
                and previous.security_policy_version
                == workspace.security_policy_version
            )
        ):
            raise UniqueConstraintViolation(
                "workspace creation identity is immutable and policy text requires a new version"
            )
        await self._save(RISK_WORKSPACES, workspace.id, workspace, workspace_to_document)

    async def list_for_user(self, user_id: str) -> tuple[RiskWorkspace, ...]:
        memberships = await self._session.query(
            MEMBERSHIPS,
            (
                QueryFilter("record_kind", "membership"),
                QueryFilter("user_id", user_id),
                QueryFilter("status", MembershipStatus.ACTIVE.value),
            ),
        )
        workspaces = []
        for stored in memberships:
            membership = _decode_stored(stored, membership_from_document)
            workspace = await self.get(membership.risk_workspace_id)
            if workspace is not None:
                workspaces.append(workspace)
        return tuple(sorted(workspaces, key=lambda value: value.id))


class FirestoreMembershipRepository(_Repository):
    async def get(self, risk_workspace_id: str, user_id: str) -> Membership | None:
        document_id = membership_id_for(risk_workspace_id, user_id)
        document = await self._session.get(MEMBERSHIPS, document_id)
        if document is None:
            return None
        return _decode_kind(document_id, document, "membership", membership_from_document)

    async def get_invitation(self, invitation_id: str) -> MembershipInvitation | None:
        document = await self._session.get(MEMBERSHIPS, invitation_id)
        if document is None:
            return None
        return _decode_kind(
            invitation_id,
            document,
            "membership_invitation",
            invitation_from_document,
        )

    async def add(self, membership: Membership) -> None:
        if membership.id != membership_id_for(
            membership.risk_workspace_id, membership.user_id
        ):
            raise UniqueConstraintViolation("membership id is not canonical")
        await self._add(MEMBERSHIPS, membership.id, membership, membership_to_document)

    async def save(self, membership: Membership) -> None:
        previous = await _required(
            self.get(membership.risk_workspace_id, membership.user_id),
            "membership",
            membership.id,
        )
        if previous.id != membership.id:
            raise UniqueConstraintViolation("membership identity fields are immutable")
        await self._save(MEMBERSHIPS, membership.id, membership, membership_to_document)

    async def add_invitation(self, invitation: MembershipInvitation) -> None:
        await self._add(MEMBERSHIPS, invitation.id, invitation, invitation_to_document)

    async def save_invitation(self, invitation: MembershipInvitation) -> None:
        previous = await _required(
            self.get_invitation(invitation.id), "membership invitation", invitation.id
        )
        if (
            previous.risk_workspace_id != invitation.risk_workspace_id
            or previous.email != invitation.email
        ):
            raise UniqueConstraintViolation("membership invitation identity fields are immutable")
        await self._save(MEMBERSHIPS, invitation.id, invitation, invitation_to_document)

    async def list_members(self, risk_workspace_id: str) -> tuple[Membership, ...]:
        return await self._query(
            MEMBERSHIPS,
            (
                QueryFilter("record_kind", "membership"),
                QueryFilter("risk_workspace_id", risk_workspace_id),
            ),
            membership_from_document,
        )

    async def list_invitations(
        self, risk_workspace_id: str
    ) -> tuple[MembershipInvitation, ...]:
        return await self._query(
            MEMBERSHIPS,
            (
                QueryFilter("record_kind", "membership_invitation"),
                QueryFilter("risk_workspace_id", risk_workspace_id),
            ),
            invitation_from_document,
        )

    async def list_invitations_for_email(
        self, email: str
    ) -> tuple[MembershipInvitation, ...]:
        return await self._query(
            MEMBERSHIPS,
            (
                QueryFilter("record_kind", "membership_invitation"),
                QueryFilter("email", normalize_invitation_email(email)),
            ),
            invitation_from_document,
        )


class FirestoreSourceMetadataRepository(_Repository):
    async def get_connection(self, connection_id: str) -> SourceConnection | None:
        return await self._get(
            SOURCE_CONNECTIONS, connection_id, source_connection_from_document
        )

    async def add_connection(self, connection: SourceConnection) -> None:
        await self._add(
            SOURCE_CONNECTIONS, connection.id, connection, source_connection_to_document
        )

    async def save_connection(self, connection: SourceConnection) -> None:
        await self._save(
            SOURCE_CONNECTIONS, connection.id, connection, source_connection_to_document
        )

    async def get_source_workspace(self, source_workspace_id: str) -> SourceWorkspace | None:
        return await self._get(
            SOURCE_WORKSPACES, source_workspace_id, source_workspace_from_document
        )

    async def add_source_workspace(self, source_workspace: SourceWorkspace) -> None:
        await self._add(
            SOURCE_WORKSPACES,
            source_workspace.id,
            source_workspace,
            source_workspace_to_document,
        )

    async def save_source_workspace(self, source_workspace: SourceWorkspace) -> None:
        await self._save(
            SOURCE_WORKSPACES,
            source_workspace.id,
            source_workspace,
            source_workspace_to_document,
        )


class FirestoreMountRepository(_Repository):
    async def get(self, mount_id: str) -> WorkspaceMount | None:
        return await self._get(WORKSPACE_MOUNTS, mount_id, mount_from_document)

    async def add(self, mount: WorkspaceMount) -> None:
        await claim_unique_key(
            self._session,
            collection=WORKSPACE_MOUNTS,
            namespace="workspace-alias",
            components=(mount.risk_workspace_id, mount_alias_key(mount.alias)),
            owner_document_id=mount.id,
        )
        await claim_unique_key(
            self._session,
            collection=WORKSPACE_MOUNTS,
            namespace="source-workspace",
            components=(mount.source_workspace_id,),
            owner_document_id=mount.id,
        )
        await self._add(WORKSPACE_MOUNTS, mount.id, mount, mount_to_document)

    async def save(self, mount: WorkspaceMount) -> None:
        previous = await _required(self.get(mount.id), "mount", mount.id)
        if previous.risk_workspace_id != mount.risk_workspace_id:
            raise UniqueConstraintViolation("a mount cannot move between virtual workspaces")
        if previous.source_workspace_id != mount.source_workspace_id:
            raise UniqueConstraintViolation("a mount cannot change its source workspace")
        previous_alias = mount_alias_key(previous.alias)
        new_alias = mount_alias_key(mount.alias)
        if previous_alias != new_alias:
            await claim_unique_key(
                self._session,
                collection=WORKSPACE_MOUNTS,
                namespace="workspace-alias",
                components=(mount.risk_workspace_id, new_alias),
                owner_document_id=mount.id,
            )
            await release_unique_key(
                self._session,
                collection=WORKSPACE_MOUNTS,
                namespace="workspace-alias",
                components=(mount.risk_workspace_id, previous_alias),
                owner_document_id=mount.id,
            )
        else:
            await claim_unique_key(
                self._session,
                collection=WORKSPACE_MOUNTS,
                namespace="workspace-alias",
                components=(mount.risk_workspace_id, new_alias),
                owner_document_id=mount.id,
            )
        await claim_unique_key(
            self._session,
            collection=WORKSPACE_MOUNTS,
            namespace="source-workspace",
            components=(mount.source_workspace_id,),
            owner_document_id=mount.id,
        )
        await self._save(WORKSPACE_MOUNTS, mount.id, mount, mount_to_document)

    async def remove(self, mount_id: str) -> None:
        mount = await _required(self.get(mount_id), "mount", mount_id)
        await release_unique_key(
            self._session,
            collection=WORKSPACE_MOUNTS,
            namespace="workspace-alias",
            components=(mount.risk_workspace_id, mount_alias_key(mount.alias)),
            owner_document_id=mount.id,
        )
        await release_unique_key(
            self._session,
            collection=WORKSPACE_MOUNTS,
            namespace="source-workspace",
            components=(mount.source_workspace_id,),
            owner_document_id=mount.id,
        )
        await self._session.delete(WORKSPACE_MOUNTS, mount_id)

    async def list_for_workspace(self, risk_workspace_id: str) -> tuple[WorkspaceMount, ...]:
        return await self._query(
            WORKSPACE_MOUNTS,
            (
                QueryFilter("record_kind", "workspace_mount"),
                QueryFilter("risk_workspace_id", risk_workspace_id),
            ),
            mount_from_document,
        )

    async def list_by_custodian(
        self, risk_workspace_id: str, user_id: str
    ) -> tuple[WorkspaceMount, ...]:
        return await self._query(
            WORKSPACE_MOUNTS,
            (
                QueryFilter("record_kind", "workspace_mount"),
                QueryFilter("risk_workspace_id", risk_workspace_id),
                QueryFilter("mounted_by_user_id", user_id),
            ),
            mount_from_document,
        )

class FirestoreArtifactRepository(_Repository):
    async def get(self, artifact_id: str) -> Artifact | None:
        return await self._get(ARTIFACTS, artifact_id, artifact_from_document)

    async def get_by_source_identity(
        self, source_workspace_id: str, source_artifact_id: str
    ) -> Artifact | None:
        owner = await resolve_unique_key(
            self._session,
            collection=ARTIFACTS,
            namespace="source-identity",
            components=(source_workspace_id, source_artifact_id),
        )
        if owner is None:
            return None
        value = await self.get(owner)
        if value is None:
            raise DocumentMappingError("source-identity sentinel points to a missing artifact")
        return value

    async def add(self, artifact: Artifact, state: ArtifactState) -> None:
        if state.artifact_id != artifact.id:
            raise UniqueConstraintViolation("artifact state must belong to the added artifact")
        await claim_unique_key(
            self._session,
            collection=ARTIFACTS,
            namespace="source-identity",
            components=(artifact.source_workspace_id, artifact.source_artifact_id),
            owner_document_id=artifact.id,
        )
        await self._add(ARTIFACTS, artifact.id, artifact, artifact_to_document)
        await self._add(
            ARTIFACT_STATES,
            state.artifact_id,
            state,
            artifact_state_to_document,
        )

    async def save(self, artifact: Artifact) -> None:
        previous = await _required(self.get(artifact.id), "artifact", artifact.id)
        if previous.source_workspace_id != artifact.source_workspace_id:
            raise UniqueConstraintViolation("an artifact cannot move between source workspaces")
        previous_identity = (
            previous.source_workspace_id,
            previous.source_artifact_id,
        )
        current_identity = (artifact.source_workspace_id, artifact.source_artifact_id)
        if previous_identity != current_identity:
            await claim_unique_key(
                self._session,
                collection=ARTIFACTS,
                namespace="source-identity",
                components=current_identity,
                owner_document_id=artifact.id,
            )
            await release_unique_key(
                self._session,
                collection=ARTIFACTS,
                namespace="source-identity",
                components=previous_identity,
                owner_document_id=artifact.id,
            )
        else:
            await claim_unique_key(
                self._session,
                collection=ARTIFACTS,
                namespace="source-identity",
                components=current_identity,
                owner_document_id=artifact.id,
            )
        await self._save(ARTIFACTS, artifact.id, artifact, artifact_to_document)

    async def get_state(self, artifact_id: str) -> ArtifactState | None:
        return await self._get(
            ARTIFACT_STATES,
            artifact_id,
            artifact_state_from_document,
            identity_field="artifact_id",
        )

    async def save_state(self, state: ArtifactState) -> None:
        if await self.get(state.artifact_id) is None:
            raise RecordNotFoundError(f"artifact was not found: {state.artifact_id!r}")
        await self._save(
            ARTIFACT_STATES,
            state.artifact_id,
            state,
            artifact_state_to_document,
        )

    async def list_for_workspace(
        self, risk_workspace_id: str
    ) -> tuple[Artifact, ...]:
        return await self._query(
            ARTIFACTS,
            (QueryFilter("risk_workspace_id", risk_workspace_id),),
            artifact_from_document,
        )


class FirestoreChangeEventRepository(_Repository):
    async def get(self, change_event_id: str) -> ChangeEvent | None:
        return await self._get(CHANGE_EVENTS, change_event_id, change_event_from_document)

    async def get_by_fingerprint(self, event_fingerprint: str) -> ChangeEvent | None:
        owner = await resolve_unique_key(
            self._session,
            collection=CHANGE_EVENTS,
            namespace="event-fingerprint",
            components=(event_fingerprint,),
        )
        if owner is None:
            return None
        value = await self.get(owner)
        if value is None:
            raise DocumentMappingError(
                "event-fingerprint sentinel points to a missing change event"
            )
        return value

    async def add(self, event: ChangeEvent) -> None:
        await claim_unique_key(
            self._session,
            collection=CHANGE_EVENTS,
            namespace="event-fingerprint",
            components=(event.event_fingerprint,),
            owner_document_id=event.id,
        )
        await self._add(CHANGE_EVENTS, event.id, event, change_event_to_document)

    async def save(self, event: ChangeEvent) -> None:
        previous = await _required(self.get(event.id), "change event", event.id)
        if previous.event_fingerprint != event.event_fingerprint:
            raise UniqueConstraintViolation("change-event fingerprint is immutable")
        await claim_unique_key(
            self._session,
            collection=CHANGE_EVENTS,
            namespace="event-fingerprint",
            components=(event.event_fingerprint,),
            owner_document_id=event.id,
        )
        await self._save(CHANGE_EVENTS, event.id, event, change_event_to_document)

    async def list_for_workspace(
        self, risk_workspace_id: str
    ) -> tuple[ChangeEvent, ...]:
        return await self._query(
            CHANGE_EVENTS,
            (QueryFilter("risk_workspace_id", risk_workspace_id),),
            change_event_from_document,
        )

    async def list_for_artifact(self, artifact_id: str) -> tuple[ChangeEvent, ...]:
        return await self._query(
            CHANGE_EVENTS,
            (QueryFilter("artifact_id", artifact_id),),
            change_event_from_document,
        )


class FirestoreAnalysisJobRepository(_Repository):
    async def get(self, analysis_job_id: str) -> AnalysisJob | None:
        return await self._get(ANALYSIS_JOBS, analysis_job_id, analysis_job_from_document)

    async def add(self, job: AnalysisJob) -> None:
        await self._add(ANALYSIS_JOBS, job.id, job, analysis_job_to_document)

    async def save(self, job: AnalysisJob) -> None:
        previous = await _required(self.get(job.id), "analysis job", job.id)
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
        # 재검사는 끝난 판정을 다시 돌리는 것이 요점이므로, 이전 상태가 성공이어도
        # 새 attempt 를 열 수 있어야 한다. 예전에는 FAILED/RUNNING 만 허용해서
        # 성공한 분석에 "다시 검사" 를 누르면 여기서 막혔다. 이 불변조건이 막으려는
        # 것은 **한 attempt 안에서** 판정이 조용히 바뀌는 것이지, 새 attempt 가 아니다.
        is_attempt_reset = (
            previous.status is not AnalysisJobStatus.QUEUED
            and job.status in {AnalysisJobStatus.QUEUED, AnalysisJobStatus.RUNNING}
            and not job.analysis_outcomes
            and (
                job.status is AnalysisJobStatus.QUEUED
                or job.started_at != previous.started_at
            )
        )
        if not is_attempt_reset and any(
            job.analysis_outcomes.get(analysis_type) != outcome
            for analysis_type, outcome in previous.analysis_outcomes.items()
        ):
            raise UniqueConstraintViolation(
                "analysis job outcomes are append-only within an attempt"
            )
        await self._save(ANALYSIS_JOBS, job.id, job, analysis_job_to_document)

    async def list_for_change(self, change_event_id: str) -> tuple[AnalysisJob, ...]:
        return await self._query(
            ANALYSIS_JOBS,
            (QueryFilter("change_event_id", change_event_id),),
            analysis_job_from_document,
        )


class FirestoreRiskRepository(_Repository):
    async def get(self, risk_id: str) -> Risk | None:
        return await self._get(RISKS, risk_id, risk_from_document)

    async def get_by_key(self, risk_key: str) -> Risk | None:
        owner = await resolve_unique_key(
            self._session,
            collection=RISKS,
            namespace="risk-key",
            components=(risk_key,),
        )
        if owner is None:
            return None
        value = await self.get(owner)
        if value is None:
            raise DocumentMappingError("risk-key sentinel points to a missing risk")
        return value

    async def add(self, risk: Risk) -> None:
        await claim_unique_key(
            self._session,
            collection=RISKS,
            namespace="risk-key",
            components=(risk.risk_key,),
            owner_document_id=risk.id,
        )
        await self._add(RISKS, risk.id, risk, risk_to_document)

    async def save(self, risk: Risk) -> None:
        previous = await _required(self.get(risk.id), "risk", risk.id)
        if (
            previous.risk_key != risk.risk_key
            or previous.risk_workspace_id != risk.risk_workspace_id
            or previous.artifact_id != risk.artifact_id
            or previous.analysis_type is not risk.analysis_type
            or previous.first_seen_at != risk.first_seen_at
        ):
            raise UniqueConstraintViolation("risk canonical identity is immutable")
        if (
            risk.review_version < previous.review_version
            or risk.review_version > previous.review_version + 1
            or (
                risk.review_disposition is previous.review_disposition
                and risk.review_version != previous.review_version
            )
            or (
                risk.review_disposition is not previous.review_disposition
                and risk.review_version != previous.review_version + 1
            )
        ):
            raise UniqueConstraintViolation(
                "risk review disposition requires one review version increment"
            )
        await claim_unique_key(
            self._session,
            collection=RISKS,
            namespace="risk-key",
            components=(risk.risk_key,),
            owner_document_id=risk.id,
        )
        await self._save(RISKS, risk.id, risk, risk_to_document)

    async def list_for_artifact(
        self,
        artifact_id: str,
        analysis_type: AnalysisType,
        lifecycle_states: frozenset[RiskLifecycleState] | None = None,
    ) -> tuple[Risk, ...]:
        filters = [
            QueryFilter("record_kind", "risk"),
            QueryFilter("artifact_id", artifact_id),
            QueryFilter("analysis_type", analysis_type.value),
        ]
        if lifecycle_states is not None:
            if not lifecycle_states:
                return ()
            filters.append(
                QueryFilter(
                    "lifecycle_state",
                    tuple(sorted(state.value for state in lifecycle_states)),
                    "in",
                )
            )
        return await self._query(RISKS, tuple(filters), risk_from_document)

    async def list_for_workspace(self, risk_workspace_id: str) -> tuple[Risk, ...]:
        return await self._query(
            RISKS,
            (
                QueryFilter("record_kind", "risk"),
                QueryFilter("risk_workspace_id", risk_workspace_id),
            ),
            risk_from_document,
        )

    async def add_evidence(self, evidence: RiskEvidence) -> None:
        if await self.get(evidence.risk_id) is None:
            raise RecordNotFoundError(f"risk was not found: {evidence.risk_id!r}")
        await self._add(
            RISK_EVIDENCE, evidence.id, evidence, risk_evidence_to_document
        )

    async def clear_evidence(self, risk_id: str, analysis_job_id: str) -> int:
        """이 분석 실행이 앞서 남긴 근거를 지운다.

        근거 문서 ID 는 (Risk, 분석 실행, 근거 이름) 에서 결정된다. 같은 문서를
        다시 검사하면 분석 실행 ID 도 같으므로 ID 도 같아진다. 실행 결과는
        재검사 때 초기화되는데 근거는 남아 있어, 같은 ID 를 다시 만들려다
        충돌했다 — 배포에서 재검사가 매번 이 이유로 실패했다.
        """
        # Risk 하나로만 걸러 온 뒤 실행 ID 는 여기서 본다. 동등 조건 둘을 함께
        # 거는 질의는 색인 구성에 기대게 되고, Risk 하나의 근거는 몇 건뿐이다.
        documents = await self._session.query(
            RISK_EVIDENCE, (QueryFilter("risk_id", risk_id),)
        )
        removed = 0
        for document in documents:
            if document.data.get("analysis_job_id") != analysis_job_id:
                continue
            await self._session.delete(RISK_EVIDENCE, document.key.document_id)
            removed += 1
        return removed

    async def list_evidence(self, risk_id: str) -> tuple[RiskEvidence, ...]:
        return await self._query(
            RISK_EVIDENCE,
            (QueryFilter("risk_id", risk_id),),
            risk_evidence_from_document,
        )

    async def append_event(self, event: RiskEvent) -> None:
        if await self.get(event.risk_id) is None:
            raise RecordNotFoundError(f"risk was not found: {event.risk_id!r}")
        await self._add(RISK_EVENTS, event.id, event, risk_event_to_document)

    async def list_events(self, risk_id: str) -> tuple[RiskEvent, ...]:
        return await self._query(
            RISK_EVENTS,
            (QueryFilter("risk_id", risk_id),),
            risk_event_from_document,
            sort_key=lambda event: (event.occurred_at, event.id),
        )


class FirestoreAuditRepository(_Repository):
    async def append(self, event: AuditEvent) -> None:
        await self._add(AUDIT_EVENTS, event.id, event, audit_event_to_document)

    async def list_for_workspace(self, risk_workspace_id: str) -> tuple[AuditEvent, ...]:
        return await self._query(
            AUDIT_EVENTS,
            (QueryFilter("risk_workspace_id", risk_workspace_id),),
            audit_event_from_document,
            sort_key=lambda event: (event.occurred_at, event.id),
        )

    async def append_source_access(self, event: SourceAccessEvent) -> None:
        await self._add(
            SOURCE_ACCESS_EVENTS,
            event.id,
            event,
            source_access_event_to_document,
        )

    async def get_source_access(self, event_id: str) -> SourceAccessEvent | None:
        return await self._get(
            SOURCE_ACCESS_EVENTS,
            event_id,
            source_access_event_from_document,
        )

    async def list_source_access(
        self, risk_workspace_id: str
    ) -> tuple[SourceAccessEvent, ...]:
        return await self._query(
            SOURCE_ACCESS_EVENTS,
            (QueryFilter("risk_workspace_id", risk_workspace_id),),
            source_access_event_from_document,
            sort_key=lambda event: (event.occurred_at, event.id),
        )


class FirestoreNotificationRepository(_Repository):
    async def get(self, notification_id: str) -> Notification | None:
        return await self._get(NOTIFICATIONS, notification_id, notification_from_document)

    async def add(self, notification: Notification) -> None:
        await self._add(
            NOTIFICATIONS, notification.id, notification, notification_to_document
        )

    async def save(self, notification: Notification) -> None:
        previous = await _required(
            self.get(notification.id), "notification", notification.id
        )
        if (
            previous.user_id != notification.user_id
            or previous.risk_workspace_id != notification.risk_workspace_id
            or previous.notification_type is not notification.notification_type
            or previous.created_at != notification.created_at
            or previous.metadata_safe != notification.metadata_safe
            or (
                previous.status is NotificationStatus.READ
                and (
                    notification.status is not NotificationStatus.READ
                    or notification.read_at != previous.read_at
                )
            )
        ):
            raise UniqueConstraintViolation(
                "notification identity is immutable and READ cannot become UNREAD"
            )
        await self._save(
            NOTIFICATIONS, notification.id, notification, notification_to_document
        )

    async def list_for_user(self, user_id: str) -> tuple[Notification, ...]:
        return await self._query(
            NOTIFICATIONS,
            (QueryFilter("user_id", user_id),),
            notification_from_document,
            sort_key=lambda item: (item.created_at, item.id),
        )


class FirestoreControlUnitOfWork:
    def __init__(self, backend: FirestoreDocumentBackend) -> None:
        self._backend = backend
        self._session: FirestoreDocumentSession | None = None

    async def __aenter__(self) -> "FirestoreControlUnitOfWork":
        if self._session is not None:
            raise TransactionClosedError("Firestore unit of work cannot be reused")
        self._session = FirestoreDocumentSession(self._backend)
        self.users = FirestoreUserRepository(self._session)
        self.workspaces = FirestoreWorkspaceRepository(self._session)
        self.memberships = FirestoreMembershipRepository(self._session)
        self.source_metadata = FirestoreSourceMetadataRepository(self._session)
        self.mounts = FirestoreMountRepository(self._session)
        self.artifacts = FirestoreArtifactRepository(self._session)
        self.change_events = FirestoreChangeEventRepository(self._session)
        self.analysis_jobs = FirestoreAnalysisJobRepository(self._session)
        self.risks = FirestoreRiskRepository(self._session)
        self.audit = FirestoreAuditRepository(self._session)
        self.notifications = FirestoreNotificationRepository(self._session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._session is not None and self._session.is_open:
            await self.rollback()

    async def commit(self) -> None:
        await self._required_session().commit()

    async def rollback(self) -> None:
        await self._required_session().rollback()

    def _required_session(self) -> FirestoreDocumentSession:
        if self._session is None:
            raise TransactionClosedError("Firestore unit of work is not active")
        return self._session


class FirestoreControlUnitOfWorkFactory:
    def __init__(self, backend: FirestoreDocumentBackend) -> None:
        self._backend = backend

    @classmethod
    def from_client(cls, client, *, max_attempts: int = 5):
        return cls(GoogleFirestoreBackend(client, max_attempts=max_attempts))

    def __call__(self) -> FirestoreControlUnitOfWork:
        return FirestoreControlUnitOfWork(self._backend)


async def _required(awaitable, kind: str, key: str):
    value = await awaitable
    if value is None:
        raise RecordNotFoundError(f"{kind} was not found: {key!r}")
    return value


def _decode_stored(
    stored: StoredDocument,
    decoder: Decoder,
    *,
    identity_field: str = "id",
):
    value = decoder(stored.data)
    if getattr(value, identity_field) != stored.key.document_id:
        raise DocumentMappingError(
            f"document path identity does not match {identity_field}: "
            f"{stored.key.collection}/{stored.key.document_id}"
        )
    return value


def _decode_kind(
    document_id: str,
    document: Mapping[str, object],
    expected_kind: str,
    decoder: Decoder,
):
    if document.get("record_kind") != expected_kind:
        raise DocumentMappingError(
            f"memberships/{document_id} has unexpected record_kind: "
            f"{document.get('record_kind')!r}"
        )
    value = decoder(document)
    if value.id != document_id:
        raise DocumentMappingError(
            f"document path identity does not match id: memberships/{document_id}"
        )
    return value


__all__ = [
    "FirestoreControlUnitOfWork",
    "FirestoreControlUnitOfWorkFactory",
]
