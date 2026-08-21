"""Stable Integration-facing facade over Control Plane application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from iprisk_contracts import (
    AnalysisResult,
    MountRef,
    SourceArtifactRef,
    SourceChange,
    SourceSnapshot,
)

from ip_risk_agent.application.analysis_jobs.service import (
    AnalysisJobOrchestrationService,
)
from ip_risk_agent.application.observability import CorrelationIds, StructuredLogger
from ip_risk_agent.application.process_change.queue import TaskEnqueuer
from ip_risk_agent.application.process_change.service import SourceChangeIntakeService
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.risk_reconcile import AnalysisResultIntakeService
from ip_risk_agent.application.risk_reconcile.retention import (
    sanitize_failure_message,
)
from ip_risk_agent.application.security_gate import (
    SecurityGatePolicy,
    SecurityGateService,
    SourceScopeDecision,
)
from ip_risk_agent.core.artifacts import Artifact
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
from ip_risk_agent.core.auth import UserStatus
from ip_risk_agent.core.common import (
    ActorType,
    DomainInvariantError,
    normalize_utc,
    stable_key,
)
from ip_risk_agent.core.memberships import (
    AuthorizationDecision,
    VwsAction,
    authorize_vws_action,
    require_authorized,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.workspaces import RiskWorkspaceStatus

from .models import (
    AnalysisArtifactBuildResult,
    AnalysisExecutionClaim,
    AnalysisResultReceipt,
    ControlPlaneFacadeConfig,
    FacadeAuthorizationDecision,
    OriginalSourceRequest,
    PublicVwsAction,
    SourceAccessReceiptContext,
    SourceAccessRegistration,
    SourceChangeReceipt,
    SourceMetadataRegistration,
    SourceMetadataRegistrationCommand,
    SourceScopeInput,
    SourceWorkspaceContext,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class _CanonicalPolicyResolver:
    config: ControlPlaneFacadeConfig

    def resolve(self, risk_workspace_id: str, policy_version: str) -> SecurityGatePolicy:
        del risk_workspace_id
        return self.config.security_gate._build(policy_version)


class ControlPlaneFacade:
    """The only supported import surface for cross-plane Control orchestration."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        task_enqueuer: TaskEnqueuer,
        clock: Clock,
        id_factory: IdFactory,
        config: ControlPlaneFacadeConfig,
        observer: StructuredLogger | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._config = config
        self._observer = observer or StructuredLogger()
        self._retention_policy = config.evidence_retention._build()
        self._source_changes = SourceChangeIntakeService(
            unit_of_work_factory=unit_of_work_factory,
            task_enqueuer=task_enqueuer,
            clock=clock,
            requested_analysis_types=config.requested_analysis_types,
            retry_failed_events=config.retry_failed_events,
            concurrency_attempts=config.concurrency_attempts,
        )
        self._jobs = AnalysisJobOrchestrationService(
            unit_of_work_factory=unit_of_work_factory,
            task_enqueuer=task_enqueuer,
            clock=clock,
            concurrency_attempts=config.concurrency_attempts,
        )
        self._security_gate = SecurityGateService(
            unit_of_work_factory=unit_of_work_factory,
            policy_resolver=_CanonicalPolicyResolver(config),
            clock=clock,
            concurrency_attempts=config.concurrency_attempts,
            use_canonical_workspace_policy_text=True,
        )
        self._analysis_results = AnalysisResultIntakeService(
            unit_of_work_factory=unit_of_work_factory,
            clock=clock,
            retention_policy=self._retention_policy,
            concurrency_attempts=config.concurrency_attempts,
        )

    async def authorize_vws_action(
        self,
        *,
        actor_user_id: str,
        risk_workspace_id: str,
        action: PublicVwsAction,
        mount_id: str | None = None,
        provider_credential_owner_user_id: str | None = None,
    ) -> FacadeAuthorizationDecision:
        decision = await self._authorize(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            action=action,
            mount_id=mount_id,
            provider_credential_owner_user_id=provider_credential_owner_user_id,
        )
        if decision is None:
            return FacadeAuthorizationDecision(False, "AUTHENTICATION_REQUIRED", False)
        return FacadeAuthorizationDecision(
            decision.allowed,
            decision.reason.value,
            decision.provider_authority_required,
        )

    async def register_source_metadata(
        self,
        command: SourceMetadataRegistrationCommand,
    ) -> SourceMetadataRegistration:
        last_conflict: Exception | None = None
        for _ in range(self._config.concurrency_attempts):
            try:
                registered = await self._register_source_metadata_once(command)
                self._observer.event(
                    "source_metadata_registered",
                    correlation=CorrelationIds(
                        risk_workspace_id=command.risk_workspace_id,
                        mount_id=registered.mount_id,
                    ),
                    source_type=command.source_type.value,
                )
                return registered
            except (ConcurrencyConflictError, UniqueConstraintViolation) as exc:
                last_conflict = exc
        assert last_conflict is not None
        raise last_conflict

    async def register_source_change(self, change: SourceChange) -> SourceChangeReceipt:
        result = await self._source_changes.register_source_change(change)
        self._observer.event(
            "source_change_registered",
            correlation=CorrelationIds(
                event_id=result.change_event_id,
                analysis_job_id=result.analysis_job_id,
                risk_workspace_id=change.risk_workspace_id,
                mount_id=change.mount_id,
                artifact_id=result.artifact_id,
            ),
            source_type=change.source_type.value,
        )
        return SourceChangeReceipt(
            change_event_id=result.change_event_id,
            artifact_id=result.artifact_id,
            analysis_job_id=result.analysis_job_id,
            disposition=result.disposition.value,
            enqueued=result.enqueued,
        )

    async def claim_analysis(
        self,
        change_event_id: str,
    ) -> AnalysisExecutionClaim | None:
        state = await self._jobs.claim(change_event_id)
        if state is None:
            self._observer.event(
                "analysis_claim_skipped",
                correlation=CorrelationIds(event_id=change_event_id),
            )
            return None
        self._observer.event(
            "analysis_claimed",
            correlation=CorrelationIds(
                event_id=state.change_event.id,
                analysis_job_id=state.analysis_job.id,
                risk_workspace_id=state.change_event.risk_workspace_id,
                mount_id=state.change_event.mount_id,
                artifact_id=state.analysis_job.artifact_id,
            ),
        )
        return AnalysisExecutionClaim(
            change_event_id=state.change_event.id,
            analysis_job_id=state.analysis_job.id,
            artifact_id=state.analysis_job.artifact_id,
            revision=state.analysis_job.revision,
            requested_analysis_types=state.analysis_job.requested_analysis_types,
            attempt=state.change_event.attempts,
        )

    async def fail_analysis(self, change_event_id: str, *, failure_safe: str) -> None:
        await self._jobs.fail(
            change_event_id,
            failure_safe=sanitize_failure_message(
                failure_safe,
                self._retention_policy,
            ),
        )

    async def retry_failed_analysis(self, change_event_id: str) -> None:
        await self._jobs.retry_failed(change_event_id)

    async def register_source_access(
        self,
        context: SourceAccessReceiptContext,
    ) -> SourceAccessRegistration:
        last_conflict: Exception | None = None
        for _ in range(self._config.concurrency_attempts):
            try:
                return await self._register_source_access_once(context)
            except (ConcurrencyConflictError, UniqueConstraintViolation) as exc:
                last_conflict = exc
        assert last_conflict is not None
        raise last_conflict

    async def build_analysis_artifact(
        self,
        snapshot: SourceSnapshot,
        analysis_job_id: str,
        *,
        source_scope: SourceScopeInput | None = None,
    ) -> AnalysisArtifactBuildResult:
        scope = source_scope or SourceScopeInput()
        result = await self._security_gate.build_analysis_artifact(
            snapshot,
            analysis_job_id,
            source_scope=SourceScopeDecision(
                in_scope=scope.in_scope,
                ignore_text=scope.ignore_text,
                denial_code_safe=scope.denial_code_safe,
            ),
        )
        self._observer.event(
            "analysis_artifact_built" if result.analysis_artifact else "analysis_artifact_denied",
            correlation=CorrelationIds(
                analysis_job_id=analysis_job_id,
                risk_workspace_id=snapshot.risk_workspace_id,
                mount_id=snapshot.mount_id,
                artifact_id=(
                    None
                    if result.analysis_artifact is None
                    else result.analysis_artifact.artifact_id
                ),
            ),
            source_type=snapshot.source_type.value,
        )
        return AnalysisArtifactBuildResult(
            analysis_artifact=result.analysis_artifact,
            denial_reason=(
                None if result.denial_reason is None else result.denial_reason.value
            ),
            source_access_event_id=result.source_access_event_id,
        )

    async def accept_analysis_result(
        self,
        result: AnalysisResult,
    ) -> AnalysisResultReceipt:
        accepted = await self._analysis_results.accept_analysis_result(result)
        self._observer.event(
            "analysis_result_accepted",
            correlation=CorrelationIds(
                analysis_job_id=result.analysis_job_id,
                artifact_id=result.artifact_id,
            ),
            analyzer_type=result.analysis_type.value,
            candidate_count=len(result.candidates),
            coverage=result.coverage.value,
            model_version=result.versions.model_id,
            prompt_version=result.versions.prompt_version,
        )
        return AnalysisResultReceipt(
            disposition=accepted.disposition.value,
            analysis_job_id=accepted.analysis_job_id,
            result_fingerprint=accepted.result_fingerprint,
            job_status=accepted.job_status.value,
            affected_risk_ids=accepted.affected_risk_ids,
            resolved_risk_ids=accepted.resolved_risk_ids,
            evidence_count=accepted.evidence_count,
        )

    async def get_mount_ref(self, mount_id: str) -> MountRef:
        async with self._unit_of_work_factory() as uow:
            mount = await uow.mounts.get(mount_id)
            if mount is None:
                raise RecordNotFoundError(f"mount was not found: {mount_id!r}")
            source_workspace = await uow.source_metadata.get_source_workspace(
                mount.source_workspace_id
            )
        if source_workspace is None or (
            source_workspace.source_connection_id != mount.source_connection_id
        ):
            raise DomainInvariantError("mount canonical source context is inconsistent")
        return MountRef(
            risk_workspace_id=mount.risk_workspace_id,
            mount_id=mount.id,
            source_workspace_id=source_workspace.id,
            source_type=source_workspace.source_type,
        )

    async def get_source_workspace_context(
        self,
        source_workspace_id: str,
    ) -> SourceWorkspaceContext:
        async with self._unit_of_work_factory() as uow:
            source_workspace = await uow.source_metadata.get_source_workspace(
                source_workspace_id
            )
            if source_workspace is None:
                raise RecordNotFoundError(
                    f"source workspace was not found: {source_workspace_id!r}"
                )
            connection = await uow.source_metadata.get_connection(
                source_workspace.source_connection_id
            )
        if connection is None or connection.provider is not source_workspace.source_type:
            raise DomainInvariantError("source workspace connection is inconsistent")
        return SourceWorkspaceContext(
            source_workspace_id=source_workspace.id,
            source_connection_id=connection.id,
            source_type=source_workspace.source_type,
            external_scope_id=source_workspace.external_scope_id,
            display_name=source_workspace.display_name,
            source_workspace_status=source_workspace.status.value,
            source_connection_status=connection.status.value,
            authorized_by_user_id=connection.authorized_by_user_id,
            provider_account_label=connection.provider_account_label,
            credential_ref=connection.credential_ref,
            tracking_config_safe=source_workspace.tracking_config_safe,
        )

    async def get_original_source_request(
        self,
        *,
        actor_user_id: str,
        risk_workspace_id: str,
        artifact_id: str,
    ) -> OriginalSourceRequest:
        decision = await self._authorize(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            action=PublicVwsAction.RISK_VIEW,
        )
        if decision is None:
            raise PermissionError("authentication is required")
        require_authorized(decision)
        async with self._unit_of_work_factory() as uow:
            artifact = await uow.artifacts.get(artifact_id)
        if artifact is None or artifact.risk_workspace_id != risk_workspace_id:
            raise RecordNotFoundError(f"artifact was not found: {artifact_id!r}")
        mount = await self.get_mount_ref(artifact.mount_id)
        return OriginalSourceRequest(
            requested_by_user_id=actor_user_id,
            mount=mount,
            artifact=SourceArtifactRef(
                source_artifact_id=artifact.source_artifact_id,
                display_name=artifact.display_name,
                path_hint=None,
            ),
        )

    async def _authorize(
        self,
        *,
        actor_user_id: str,
        risk_workspace_id: str,
        action: PublicVwsAction,
        mount_id: str | None = None,
        provider_credential_owner_user_id: str | None = None,
    ) -> AuthorizationDecision | None:
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(actor_user_id)
            if user is None or user.status is not UserStatus.ACTIVE:
                return None
            workspace = await uow.workspaces.get(risk_workspace_id)
            if workspace is None:
                raise RecordNotFoundError(
                    f"workspace was not found: {risk_workspace_id!r}"
                )
            membership = await uow.memberships.get(
                risk_workspace_id,
                actor_user_id,
            )
            mount = None
            credential_owner = provider_credential_owner_user_id
            if mount_id is not None:
                mount = await uow.mounts.get(mount_id)
                if mount is None:
                    raise RecordNotFoundError(f"mount was not found: {mount_id!r}")
                if credential_owner is None:
                    connection = await uow.source_metadata.get_connection(
                        mount.source_connection_id
                    )
                    if connection is None:
                        raise RecordNotFoundError(
                            "mount source connection was not found"
                        )
                    credential_owner = connection.authorized_by_user_id
        return authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            membership=membership,
            action=VwsAction(action.value),
            mount=mount,
            provider_credential_owner_user_id=credential_owner,
        )

    async def _register_source_metadata_once(
        self,
        command: SourceMetadataRegistrationCommand,
    ) -> SourceMetadataRegistration:
        connection_id = stable_key(
            "source-connection",
            (command.source_type.value, command.connection_key),
        )
        source_workspace_id = stable_key(
            "source-workspace",
            (connection_id, command.source_workspace_key),
        )
        mount_id = stable_key(
            "workspace-mount",
            (command.risk_workspace_id, source_workspace_id),
        )
        occurred_at = normalize_utc(self._clock(), "public_facade.clock")
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(command.actor_user_id)
            workspace = await uow.workspaces.get(command.risk_workspace_id)
            membership = await uow.memberships.get(
                command.risk_workspace_id,
                command.actor_user_id,
            )
            if user is None or user.status is not UserStatus.ACTIVE:
                raise PermissionError("active canonical user is required")
            if workspace is None:
                raise RecordNotFoundError(
                    f"workspace was not found: {command.risk_workspace_id!r}"
                )
            if workspace.status is not RiskWorkspaceStatus.ACTIVE:
                raise DomainInvariantError("source metadata requires an active workspace")
            require_authorized(
                authorize_vws_action(
                    actor_user_id=command.actor_user_id,
                    risk_workspace_id=command.risk_workspace_id,
                    membership=membership,
                    action=VwsAction.SOURCE_MOUNT,
                    provider_credential_owner_user_id=command.actor_user_id,
                )
            )

            connection = await uow.source_metadata.get_connection(connection_id)
            created_connection = connection is None
            if connection is None:
                connection = SourceConnection(
                    id=connection_id,
                    provider=command.source_type,
                    authorized_by_user_id=command.actor_user_id,
                    status=SourceConnectionStatus.ACTIVE,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                    provider_subject=command.provider_subject,
                    provider_account_label=command.provider_account_label,
                    credential_ref=command.credential_ref,
                )
                await uow.source_metadata.add_connection(connection)
            else:
                _require_connection_match(connection, command)
                if (
                    command.credential_ref is not None
                    and connection.credential_ref != command.credential_ref
                ):
                    # 재연결로 재발급된 자격증명. 옛 참조를 남겨 두면 그 뒤의
                    # 조회가 파기된 secret 을 가리킨다.
                    connection = replace(
                        connection,
                        credential_ref=command.credential_ref,
                        updated_at=occurred_at,
                    )
                    await uow.source_metadata.save_connection(connection)

            source_workspace = await uow.source_metadata.get_source_workspace(
                source_workspace_id
            )
            created_source_workspace = source_workspace is None
            if source_workspace is None:
                source_workspace = SourceWorkspace(
                    id=source_workspace_id,
                    source_connection_id=connection_id,
                    source_type=command.source_type,
                    external_scope_id=command.external_scope_id,
                    display_name=command.source_workspace_display_name,
                    status=SourceWorkspaceStatus.ACTIVE,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                    tracking_config_safe=command.tracking_config_safe,
                )
                await uow.source_metadata.add_source_workspace(source_workspace)
            else:
                _require_source_workspace_match(source_workspace, connection_id, command)

            mount = await uow.mounts.get(mount_id)
            created_mount = mount is None
            if mount is None:
                mount = WorkspaceMount(
                    id=mount_id,
                    risk_workspace_id=command.risk_workspace_id,
                    source_workspace_id=source_workspace_id,
                    alias=command.mount_alias,
                    mounted_by_user_id=command.actor_user_id,
                    source_connection_id=connection_id,
                    status=MountStatus.ACTIVE,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
                await uow.mounts.add(mount)
            else:
                _require_mount_match(mount, connection_id, source_workspace_id, command)

            registration_fingerprint = stable_key(
                "source-registration",
                (command.registration_key,),
            )
            if created_connection:
                await uow.audit.append(
                    AuditEvent(
                        id=self._id_factory("audit"),
                        risk_workspace_id=command.risk_workspace_id,
                        event_type=AuditEventType.SOURCE_CONNECTED,
                        actor_type=ActorType.USER,
                        actor_user_id=command.actor_user_id,
                        occurred_at=occurred_at,
                        metadata_safe={
                            "source_connection_id": connection_id,
                            "source_type": command.source_type.value,
                            "registration_fingerprint": registration_fingerprint,
                        },
                    )
                )
            if created_mount:
                await uow.audit.append(
                    AuditEvent(
                        id=self._id_factory("audit"),
                        risk_workspace_id=command.risk_workspace_id,
                        event_type=AuditEventType.MOUNT_CREATED,
                        actor_type=ActorType.USER,
                        actor_user_id=command.actor_user_id,
                        occurred_at=occurred_at,
                        metadata_safe={
                            "mount_id": mount_id,
                            "source_workspace_id": source_workspace_id,
                            "source_type": command.source_type.value,
                        },
                    )
                )
            if created_connection or created_source_workspace or created_mount:
                await uow.commit()
        return SourceMetadataRegistration(
            connection_id=connection_id,
            source_workspace_id=source_workspace_id,
            mount_id=mount_id,
            created_connection=created_connection,
            created_source_workspace=created_source_workspace,
            created_mount=created_mount,
        )

    async def _register_source_access_once(
        self,
        context: SourceAccessReceiptContext,
    ) -> SourceAccessRegistration:
        async with self._unit_of_work_factory() as uow:
            artifact = await uow.artifacts.get_by_source_identity(
                context.source_workspace_id,
                context.source_artifact_id,
            )
            if artifact is None:
                raise RecordNotFoundError("source access artifact was not found")
            await _validate_source_access_context(uow, artifact, context)
            event = _source_access_event(artifact, context)
            existing = await uow.audit.get_source_access(event.id)
            if existing is None:
                await uow.audit.append_source_access(event)
                await uow.commit()
                created = True
            elif existing == event:
                created = False
            else:
                raise DomainInvariantError("source access event identity collision")
        return SourceAccessRegistration(event.id, created)


def _require_connection_match(
    connection: SourceConnection,
    command: SourceMetadataRegistrationCommand,
) -> None:
    """같은 registration key 를 다른 정체성이 쓰려는 것만 막는다.

    credential_ref 는 비교하지 않는다. 사용자가 같은 계정으로 provider 를
    다시 연결하면 정체성은 그대로인 채 자격증명만 재발급된다. 그것을
    충돌로 거부하면 재연결 뒤 어떤 Mount 도 만들 수 없다. 자격증명 회전은
    호출부에서 저장값을 갱신하는 것으로 처리한다.
    """
    if (
        connection.provider is not command.source_type
        or connection.authorized_by_user_id != command.actor_user_id
        or connection.provider_subject != command.provider_subject
        or connection.provider_account_label != command.provider_account_label
    ):
        raise DomainInvariantError("source connection registration key collision")


def _require_source_workspace_match(
    source_workspace: SourceWorkspace,
    connection_id: str,
    command: SourceMetadataRegistrationCommand,
) -> None:
    if (
        source_workspace.source_connection_id != connection_id
        or source_workspace.source_type is not command.source_type
        or source_workspace.external_scope_id != command.external_scope_id
        or source_workspace.display_name != command.source_workspace_display_name
        or source_workspace.tracking_config_safe != command.tracking_config_safe
    ):
        raise DomainInvariantError("source workspace registration key collision")


def _require_mount_match(
    mount: WorkspaceMount,
    connection_id: str,
    source_workspace_id: str,
    command: SourceMetadataRegistrationCommand,
) -> None:
    if (
        mount.risk_workspace_id != command.risk_workspace_id
        or mount.source_workspace_id != source_workspace_id
        or mount.source_connection_id != connection_id
        or mount.mounted_by_user_id != command.actor_user_id
    ):
        raise DomainInvariantError("source mount registration key collision")


async def _validate_source_access_context(
    uow: ControlUnitOfWork,
    artifact: Artifact,
    context: SourceAccessReceiptContext,
) -> None:
    mount = await uow.mounts.get(context.mount_id)
    source_workspace = await uow.source_metadata.get_source_workspace(
        context.source_workspace_id
    )
    if mount is None or source_workspace is None:
        raise RecordNotFoundError("source access canonical context is incomplete")
    if (
        artifact.risk_workspace_id != context.risk_workspace_id
        or artifact.mount_id != mount.id
        or artifact.source_workspace_id != source_workspace.id
        or artifact.source_type is not context.source_type
        or mount.risk_workspace_id != context.risk_workspace_id
        or mount.source_workspace_id != source_workspace.id
        or source_workspace.source_type is not context.source_type
    ):
        raise DomainInvariantError("source access canonical context is inconsistent")
    if context.analysis_job_id is not None:
        job = await uow.analysis_jobs.get(context.analysis_job_id)
        if job is None:
            raise RecordNotFoundError("source access analysis job was not found")
        if job.artifact_id != artifact.id or job.revision != context.revision:
            raise DomainInvariantError("source access analysis context is inconsistent")


def _source_access_event(
    artifact: Artifact,
    context: SourceAccessReceiptContext,
) -> SourceAccessEvent:
    receipt = context.receipt
    provider_component = (
        "<none>"
        if receipt.provider_request_id is None
        else receipt.provider_request_id or "<empty>"
    )
    job_component = context.analysis_job_id or "<none>"
    occurred_at = normalize_utc(receipt.occurred_at, "source_access.receipt.occurred_at")
    event_id = stable_key(
        "source-access",
        (
            job_component,
            context.revision,
            receipt.access_type.value,
            provider_component,
            occurred_at.isoformat(),
            str(receipt.content_bytes),
        ),
    )
    return SourceAccessEvent(
        id=event_id,
        risk_workspace_id=context.risk_workspace_id,
        mount_id=context.mount_id,
        artifact_id=artifact.id,
        access_type=receipt.access_type,
        revision=context.revision,
        content_bytes=receipt.content_bytes,
        occurred_at=occurred_at,
        analysis_job_id=context.analysis_job_id,
        provider_request_id=receipt.provider_request_id,
    )


__all__ = ["ControlPlaneFacade"]
