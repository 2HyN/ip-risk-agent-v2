"""VWS security policy persistence, audit, and data-access summary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256

from iprisk_contracts import ReviewPriority, SourceType
from ip_risk_agent.application.analysis_jobs.models import AnalysisJobStatus
from ip_risk_agent.application.process_change.models import ChangeEventStatus
from ip_risk_agent.core.artifacts import Artifact, ArtifactAvailability

from ip_risk_agent.application.repositories import (
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.application.security_gate import parse_ipriskignore
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
from ip_risk_agent.core.common import ActorType, DomainInvariantError, normalize_utc
from ip_risk_agent.core.memberships import (
    VwsAction,
    authorize_vws_action,
    require_authorized,
)
from ip_risk_agent.core.mounts import WorkspaceMount
from ip_risk_agent.core.workspaces import RiskWorkspace

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


class SecurityPolicyConflictError(DomainInvariantError):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceSecuritySettings:
    risk_workspace_id: str
    policy_version: str
    global_ignore_text: str
    rule_count: int


@dataclass(frozen=True, slots=True)
class SecurityPolicyUpdate:
    settings: WorkspaceSecuritySettings
    changed: bool


@dataclass(frozen=True, slots=True)
class ConnectedSourceSummary:
    mount: WorkspaceMount
    source_type: SourceType | None
    provider_account_label: str | None
    tracking_scope_summary: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TrackedArtifactSummary:
    artifact: Artifact
    mount_alias: str | None
    availability: ArtifactAvailability
    latest_revision: str | None
    change_status: ChangeEventStatus | None
    analysis_status: AnalysisJobStatus | None
    risk_count: int
    active_risk_count: int
    first_risk_id: str | None
    highest_risk_priority: ReviewPriority | None


@dataclass(frozen=True, slots=True)
class DataAccessSummary:
    risk_workspace_id: str
    retention_policy_version: str
    policy_version: str
    mounts: tuple[WorkspaceMount, ...]
    connected_sources: tuple[ConnectedSourceSummary, ...]
    tracked_artifacts: tuple[TrackedArtifactSummary, ...]
    recent_access: tuple[SourceAccessEvent, ...]
    raw_source_persisted: bool = False
    analysis_artifact_persisted: bool = False
    external_rag_reference_only: bool = True


class WorkspaceSecurityService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
        id_factory: IdFactory,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory

    async def get_settings(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
    ) -> WorkspaceSecuritySettings:
        async with self._unit_of_work_factory() as uow:
            workspace = await _authorize_and_workspace(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.VWS_VIEW,
            )
        return _settings(workspace)

    async def update_ignore_policy(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        expected_policy_version: str,
        global_ignore_text: str,
    ) -> SecurityPolicyUpdate:
        normalized = global_ignore_text.replace("\r\n", "\n").replace("\r", "\n")
        async with self._unit_of_work_factory() as uow:
            workspace = await _authorize_and_workspace(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.VWS_SECURITY_MANAGE,
            )
            rules = parse_ipriskignore(normalized)
            if workspace.security_policy_version != expected_policy_version:
                raise SecurityPolicyConflictError("security policy version conflict")
            if workspace.global_ignore_text == normalized:
                return SecurityPolicyUpdate(_settings(workspace), changed=False)
            digest = sha256(normalized.encode("utf-8")).hexdigest()
            policy_version = f"security:v1:{digest}"
            occurred_at = max(
                normalize_utc(self._clock(), "security_policy.clock"),
                workspace.updated_at,
            )
            workspace = replace(
                workspace,
                security_policy_version=policy_version,
                global_ignore_text=normalized,
                updated_at=occurred_at,
            )
            await uow.workspaces.save(workspace)
            await uow.audit.append(
                AuditEvent(
                    id=self._id_factory("audit"),
                    risk_workspace_id=risk_workspace_id,
                    event_type=AuditEventType.SECURITY_POLICY_CHANGED,
                    actor_type=ActorType.USER,
                    actor_user_id=actor_user_id,
                    occurred_at=occurred_at,
                    metadata_safe={
                        "policy_version": policy_version,
                        "rule_count": len(rules),
                    },
                )
            )
            await uow.commit()
        return SecurityPolicyUpdate(_settings(workspace), changed=True)

    async def get_data_access_summary(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        access_limit: int = 20,
    ) -> DataAccessSummary:
        if isinstance(access_limit, bool) or not 1 <= access_limit <= 100:
            raise ValueError("access_limit must be between 1 and 100")
        async with self._unit_of_work_factory() as uow:
            workspace = await _authorize_and_workspace(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.VWS_VIEW,
            )
            mounts = await uow.mounts.list_for_workspace(risk_workspace_id)
            connected_sources = []
            for mount in mounts:
                source_workspace = await uow.source_metadata.get_source_workspace(
                    mount.source_workspace_id
                )
                connection = await uow.source_metadata.get_connection(
                    mount.source_connection_id
                )
                connected_sources.append(
                    ConnectedSourceSummary(
                        mount=mount,
                        source_type=(
                            None if source_workspace is None else source_workspace.source_type
                        ),
                        provider_account_label=(
                            None
                            if connection is None
                            else connection.provider_account_label
                        ),
                        tracking_scope_summary=(
                            {}
                            if source_workspace is None
                            else source_workspace.tracking_config_safe
                        ),
                    )
                )
            access = await uow.audit.list_source_access(risk_workspace_id)
            artifacts = await uow.artifacts.list_for_workspace(risk_workspace_id)
            changes = await uow.change_events.list_for_workspace(risk_workspace_id)
            risks = await uow.risks.list_for_workspace(risk_workspace_id)
            changes_by_artifact = {}
            for change in changes:
                if change.artifact_id is None:
                    continue
                previous = changes_by_artifact.get(change.artifact_id)
                if previous is None or (change.updated_at, change.id) > (
                    previous.updated_at,
                    previous.id,
                ):
                    changes_by_artifact[change.artifact_id] = change
            risks_by_artifact: dict[str, list] = {}
            for risk in risks:
                risks_by_artifact.setdefault(risk.artifact_id, []).append(risk)
            tracked_artifacts = []
            mounts_by_id = {mount.id: mount for mount in mounts}
            for artifact in artifacts:
                state = await uow.artifacts.get_state(artifact.id)
                change = changes_by_artifact.get(artifact.id)
                jobs = (
                    ()
                    if change is None
                    else await uow.analysis_jobs.list_for_change(change.id)
                )
                latest_job = max(jobs, key=lambda job: (job.created_at, job.id), default=None)
                artifact_risks = risks_by_artifact.get(artifact.id, [])
                active_risks = [
                    risk
                    for risk in artifact_risks
                    if risk.lifecycle_state.value != "RESOLVED"
                ]
                first_risk = max(
                    artifact_risks,
                    key=lambda risk: (risk.updated_at, risk.id),
                    default=None,
                )
                highest_priority = max(
                    (risk.review_priority for risk in active_risks),
                    key=lambda value: {
                        ReviewPriority.LOW: 0,
                        ReviewPriority.MEDIUM: 1,
                        ReviewPriority.HIGH: 2,
                    }[value],
                    default=None,
                )
                tracked_artifacts.append(
                    TrackedArtifactSummary(
                        artifact=artifact,
                        mount_alias=(
                            None
                            if artifact.mount_id not in mounts_by_id
                            else mounts_by_id[artifact.mount_id].alias
                        ),
                        availability=(
                            ArtifactAvailability.UNAVAILABLE
                            if state is None
                            else state.availability_state
                        ),
                        latest_revision=None if state is None else state.latest_revision,
                        change_status=None if change is None else change.status,
                        analysis_status=None if latest_job is None else latest_job.status,
                        risk_count=len(artifact_risks),
                        active_risk_count=len(active_risks),
                        first_risk_id=None if first_risk is None else first_risk.id,
                        highest_risk_priority=highest_priority,
                    )
                )
        recent = tuple(
            sorted(access, key=lambda event: (event.occurred_at, event.id), reverse=True)[
                :access_limit
            ]
        )
        return DataAccessSummary(
            risk_workspace_id=risk_workspace_id,
            retention_policy_version=workspace.retention_policy_version,
            policy_version=workspace.security_policy_version,
            mounts=mounts,
            connected_sources=tuple(connected_sources),
            tracked_artifacts=tuple(
                sorted(
                    tracked_artifacts,
                    key=lambda item: (item.artifact.last_seen_at, item.artifact.id),
                    reverse=True,
                )
            ),
            recent_access=recent,
        )


async def _authorize_and_workspace(
    uow: ControlUnitOfWork,
    *,
    risk_workspace_id: str,
    actor_user_id: str,
    action: VwsAction,
) -> RiskWorkspace:
    workspace = await uow.workspaces.get(risk_workspace_id)
    if workspace is None:
        raise RecordNotFoundError(f"workspace was not found: {risk_workspace_id!r}")
    membership = await uow.memberships.get(risk_workspace_id, actor_user_id)
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            membership=membership,
            action=action,
        )
    )
    return workspace


def _settings(workspace: RiskWorkspace) -> WorkspaceSecuritySettings:
    return WorkspaceSecuritySettings(
        risk_workspace_id=workspace.id,
        policy_version=workspace.security_policy_version,
        global_ignore_text=workspace.global_ignore_text,
        rule_count=len(parse_ipriskignore(workspace.global_ignore_text)),
    )


__all__ = [
    "ConnectedSourceSummary",
    "DataAccessSummary",
    "SecurityPolicyConflictError",
    "SecurityPolicyUpdate",
    "WorkspaceSecurityService",
    "WorkspaceSecuritySettings",
]
