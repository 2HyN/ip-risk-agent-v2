"""Stable Integration-facing facade over Control Plane application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from iprisk_contracts import (
    AnalysisResult,
    AnalysisType,
    MountRef,
    SourceArtifactRef,
    SourceChange,
    SourceHealth,
    SourceHealthStatus,
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
from ip_risk_agent.application.risk_exclusion import exclude_artifact_risks
from ip_risk_agent.core.artifacts import Artifact, ArtifactStatus
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
from ip_risk_agent.core.workspaces.license_profile import WorkspaceLicensePolicy
from ip_risk_agent.intelligence.license import policy as license_policy

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
    UntrackedArtifact,
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
            lease_duration=timedelta(seconds=config.analysis_lease_seconds),
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
        *,
        allow_retry: bool = False,
    ) -> AnalysisExecutionClaim | None:
        state = await self._jobs.claim(change_event_id, allow_retry=allow_retry)
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
        if state.change_event.lease_expires_at is None:
            raise DomainInvariantError("claimed analysis is missing a bounded lease")
        return AnalysisExecutionClaim(
            change_event_id=state.change_event.id,
            analysis_job_id=state.analysis_job.id,
            artifact_id=state.analysis_job.artifact_id,
            revision=state.analysis_job.revision,
            requested_analysis_types=state.analysis_job.requested_analysis_types,
            attempt=state.change_event.attempts,
            lease_expires_at=state.change_event.lease_expires_at,
            source_change=state.change_event.source_change,
        )

    async def newer_change_exists(self, claim: AnalysisExecutionClaim) -> bool:
        """이 실행보다 뒤에 관측된 변경이 같은 artifact 에 있는가.

        있으면 이 실행의 결과는 어차피 버려진다 — 옛 판본의 내용으로 현재 상태를
        덮을 수 없기 때문이다. 그런데 그 판정은 지금까지 **분석이 끝난 뒤** 결과를
        받는 자리에서 났다. 그때는 KIPRIS 호출과 모델 호출을 이미 다 쓴 뒤다.

        한 번의 편집으로 Drive 가 판본 네 개를 만들었을 때 분석 네 개가 돌았고,
        셋은 그렇게 값을 치르고 버려졌다. 시작 전에 알 수 있으면 치르지 않는다.

        비교는 관측 시각으로 한다. 판본 문자열은 provider 마다 형식이 달라 순서를
        말해 주지 않는다.
        """
        async with self._unit_of_work_factory() as uow:
            events = await uow.change_events.list_for_artifact(claim.artifact_id)
        mine = claim.source_change.observed_at
        return any(
            event.id != claim.change_event_id and event.observed_at > mine
            for event in events
        )

    async def fail_analysis(
        self,
        change_event_id: str,
        *,
        failure_safe: str,
        attempt: int | None = None,
    ) -> None:
        await self._jobs.fail(
            change_event_id,
            failure_safe=sanitize_failure_message(
                failure_safe,
                self._retention_policy,
            ),
            attempt=attempt,
        )

    async def retry_failed_analysis(self, change_event_id: str) -> None:
        await self._jobs.retry_failed(change_event_id)

    async def request_reanalysis(self, change_event_id: str) -> None:
        """변경 없이 다시 검사한다. 진행 중이면 거부한다."""
        await self._jobs.request_reanalysis(change_event_id)
        self._observer.event(
            "analysis_reanalysis_requested",
            correlation=CorrelationIds(event_id=change_event_id),
        )

    async def workspace_license_policy(
        self, risk_workspace_id: str
    ) -> WorkspaceLicensePolicy | None:
        """이 workspace 의 라이선스 판정 정책 (§5.10).

        분석기 안에서 값이 필요한데 **분석기는 workspace 를 모른다.** 계약을 고치지
        않고 다리를 놓는 방법이 이미 있다 — 특허 쪽 ``previously_matched_patents`` 와
        같은 모양으로 함수 하나를 넘긴다.

        workspace 를 못 찾으면 ``None`` 이다. 그때 분석기는 **설정 안 된 것**으로 보고
        4·5 단계를 돌리지 않는다. 못 찾은 것을 "설정됐다" 로 읽으면 근거 없는 축으로
        등급이 매겨진다.
        """
        async with self._unit_of_work_factory() as uow:
            workspace = await uow.workspaces.get(risk_workspace_id)
        if workspace is None:
            return None
        return WorkspaceLicensePolicy(
            risk_workspace_id=workspace.id,
            policy_table_version=license_policy.POLICY_VERSION,
            profile=workspace.license_profile,
        )

    async def previously_matched_patents(
        self, artifact_id: str, *, limit: int = 20
    ) -> tuple[str, ...]:
        """이 artifact 에서 이미 매칭된 특허 출원번호.

        분석기가 검색 결과와 무관하게 이것들을 다시 대조한다. 그러지 않으면
        검색어가 조금만 달라져도 이전 후보가 결과에서 빠지고, 그것을 "판정해 보니
        더 이상 위험이 아니다" 로 읽어 Risk 가 조용히 RESOLVED 가 된다.

        해소된 Risk 도 포함한다. 다시 겹치면 REOPENED 로 살아나야 한다.

        risk_key 는 해시라 출원번호를 되돌릴 수 없다. 근거 ID
        (``patent:{출원번호}:claim:N``) 에서 읽는다.
        """
        numbers: list[str] = []
        async with self._unit_of_work_factory() as uow:
            risks = await uow.risks.list_for_artifact(artifact_id, AnalysisType.PATENT)
            for risk in risks:
                for evidence in await uow.risks.list_evidence(
                    risk.id, analysis_job_id=risk.latest_analysis_job_id
                ):
                    parts = evidence.evidence_id_from_result.split(":")
                    if len(parts) >= 2 and parts[0] == "patent" and parts[1]:
                        if parts[1] not in numbers:
                            numbers.append(parts[1])
                if len(numbers) >= limit:
                    break
        return tuple(numbers[:limit])

    async def untrack_artifact(
        self,
        *,
        risk_workspace_id: str,
        artifact_id: str,
    ) -> UntrackedArtifact:
        """파일 하나를 추적 대상에서 뺀다. 지우지 않는다.

        artifact 를 ``ARCHIVED`` 로 닫고 그 Risk 를 ``EXCLUDED`` 로 옮긴다. 근거와
        이력은 남으므로 나중에도 왜 그 판단을 했는지 되짚을 수 있다. 사용자가 스스로
        내린 처분이 아니라 추적이 끊겨 관리가 끝난 것이므로 ``ACCEPTED_RISK`` 가 아니라
        ``EXCLUDED`` 다.

        provider 쪽 감시를 실제로 끊는 것은 호출자(connector) 몫이다. 추적 범위의
        모양은 source 종류마다 다르고 canonical 상태가 아니다. 그래서 여기서는
        ``source_artifact_id`` 를 돌려준다.

        인가는 호출 경로가 이미 mount 범위로 확인한다
        (``SessionSourceAuthorizer`` 의 ``MOUNT_SOURCE_OPERATION``).
        """
        occurred_at = self._clock()
        async with self._unit_of_work_factory() as uow:
            artifact = await uow.artifacts.get(artifact_id)
            if artifact is None or artifact.risk_workspace_id != risk_workspace_id:
                raise RecordNotFoundError("artifact was not found in this workspace")
            already_archived = artifact.status is ArtifactStatus.ARCHIVED
            if not already_archived:
                # last_seen_at 은 건드리지 않는다. 보관은 파일을 다시 본 것이 아니다.
                await uow.artifacts.save(
                    replace(artifact, status=ArtifactStatus.ARCHIVED)
                )
            excluded_risk_ids = await exclude_artifact_risks(
                uow,
                risk_workspace_id=risk_workspace_id,
                artifact_id=artifact_id,
                occurred_at=occurred_at,
                reason_safe="artifact tracking was stopped",
                id_factory=self._id_factory,
            )
            await uow.commit()
        self._observer.event(
            "artifact_untracked",
            correlation=CorrelationIds(
                risk_workspace_id=risk_workspace_id,
                artifact_id=artifact_id,
                mount_id=artifact.mount_id,
            ),
        )
        return UntrackedArtifact(
            artifact_id=artifact_id,
            mount_id=artifact.mount_id,
            source_artifact_id=artifact.source_artifact_id,
            excluded_risk_ids=tuple(excluded_risk_ids),
            already_archived=already_archived,
        )

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
            # 거부 사유를 남기지 않으면 화면에는 INCONCLUSIVE 만 보이고 왜 막혔는지
            # 알 수 없다. 열거형 값이라 본문이나 경로가 새지 않는다.
            diagnostic_code=(
                None if result.denial_reason is None else result.denial_reason.value
            ),
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

    async def record_source_health(self, mount_id: str, health: SourceHealth) -> None:
        """Converge provider health into canonical source status idempotently."""

        occurred_at = normalize_utc(health.checked_at, "source_health.checked_at")
        async with self._unit_of_work_factory() as uow:
            mount = await uow.mounts.get(mount_id)
            if mount is None:
                raise RecordNotFoundError(f"mount was not found: {mount_id!r}")
            source_workspace = await uow.source_metadata.get_source_workspace(
                mount.source_workspace_id
            )
            connection = await uow.source_metadata.get_connection(
                mount.source_connection_id
            )
            if source_workspace is None or connection is None:
                raise DomainInvariantError("mount canonical source context is inconsistent")
            if (
                mount.status is MountStatus.DISABLED
                or source_workspace.status is SourceWorkspaceStatus.DISABLED
                or connection.status is SourceConnectionStatus.DISABLED
            ):
                return

            connection_status, workspace_status, mount_status = _health_statuses(
                health.status
            )
            if connection.status is not connection_status:
                await uow.source_metadata.save_connection(
                    replace(
                        connection,
                        status=connection_status,
                        updated_at=occurred_at,
                    )
                )
            if source_workspace.status is not workspace_status:
                await uow.source_metadata.save_source_workspace(
                    replace(
                        source_workspace,
                        status=workspace_status,
                        updated_at=occurred_at,
                    )
                )
            if mount.status is not mount_status:
                await uow.mounts.save(
                    replace(mount, status=mount_status, updated_at=occurred_at)
                )
            await uow.commit()

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
            rotated_credential = False
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
                    # 재연결로 재발급된 자격증명이다. 옛 참조를 그대로 두면 이후의
                    # 조회가 폐기된 secret 을 가리킨다.
                    connection = replace(
                        connection,
                        credential_ref=command.credential_ref,
                        updated_at=occurred_at,
                    )
                    await uow.source_metadata.save_connection(connection)
                    rotated_credential = True

            source_workspace = await uow.source_metadata.get_source_workspace(
                source_workspace_id
            )
            created_source_workspace = source_workspace is None
            updated_tracking = False
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
                if source_workspace.tracking_config_safe != command.tracking_config_safe:
                    # 추적 범위는 정체성이 아니라 상태다. 사용자가 같은 source 에
                    # 파일을 더 추가하거나 빼면 정당하게 바뀐다. 이것을 collision 으로
                    # 거부하면 한 번 만든 source workspace 에 아무것도 더할 수 없다.
                    source_workspace = replace(
                        source_workspace,
                        tracking_config_safe=command.tracking_config_safe,
                        updated_at=occurred_at,
                    )
                    await uow.source_metadata.save_source_workspace(source_workspace)
                    updated_tracking = True

            mount = await uow.mounts.get(mount_id)
            created_mount = mount is None
            reactivated_mount = False
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
                if mount.status is MountStatus.DISABLED:
                    # 소스를 다시 연결하는 것은 "다시 감시하겠다" 는 뜻이다. mount
                    # 상태는 정체성이 아니라 상태이며, DISABLED 로 남겨 두면 이후의
                    # SourceChange 가 전부 "mount is not processable" 로 거부된다.
                    # 계정 단위 정체성 때문에 재연결은 같은 mount 로 수렴하므로,
                    # 여기서 되살리지 않으면 한 번 끈 소스는 다시 켤 수 없다.
                    mount = replace(
                        mount, status=MountStatus.ACTIVE, updated_at=occurred_at
                    )
                    await uow.mounts.save(mount)
                    reactivated_mount = True

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
            # 자격증명 회전만 일어난 재연결도 반드시 커밋해야 한다. 빼면 새 참조가
            # 조용히 버려지고 이후 조회가 폐기된 secret 을 계속 가리킨다.
            if (
                created_connection
                or created_source_workspace
                or created_mount
                or rotated_credential
                or updated_tracking
                or reactivated_mount
            ):
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
    """같은 registration key 를 **다른 정체성**이 쓰려는 것만 막는다.

    ``credential_ref`` 는 비교하지 않는다. canonical connection id 는
    ``(source_type, provider_subject)`` 에서 파생되므로, 사용자가 같은 계정으로
    provider 를 다시 연결하면 정체성은 그대로인 채 자격증명만 재발급된다.
    그것을 충돌로 거부하면 **재연결 이후 어떤 Mount 도 만들 수 없다.**
    자격증명 회전은 호출부에서 저장값을 갱신하는 것으로 처리한다.
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
    ):
        raise DomainInvariantError("source workspace registration key collision")


def _health_statuses(
    status: SourceHealthStatus,
) -> tuple[SourceConnectionStatus, SourceWorkspaceStatus, MountStatus]:
    if status is SourceHealthStatus.HEALTHY:
        return (
            SourceConnectionStatus.ACTIVE,
            SourceWorkspaceStatus.ACTIVE,
            MountStatus.ACTIVE,
        )
    if status in {
        SourceHealthStatus.REAUTH_REQUIRED,
        SourceHealthStatus.PERMISSION_DENIED,
    }:
        return (
            SourceConnectionStatus.REAUTH_REQUIRED,
            SourceWorkspaceStatus.REAUTH_REQUIRED,
            MountStatus.REAUTH_REQUIRED,
        )
    if status in {SourceHealthStatus.OFFLINE, SourceHealthStatus.DEGRADED}:
        return (
            SourceConnectionStatus.DISCONNECTED,
            SourceWorkspaceStatus.SOURCE_OFFLINE,
            MountStatus.SOURCE_OFFLINE,
        )
    return (
        SourceConnectionStatus.DISABLED,
        SourceWorkspaceStatus.DISABLED,
        MountStatus.DISABLED,
    )


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
