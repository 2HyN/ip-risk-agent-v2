"""Single transient SourceSnapshot to approved AnalysisArtifact boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath

from iprisk_contracts import (
    AnalysisArtifact,
    AnalysisSecurityContext,
    AnalysisType,
    ArtifactKind,
    ContentScope,
    SourceSnapshot,
    TextSegment,
)

from ip_risk_agent.application.analysis_jobs.models import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.analysis_jobs.transitions import complete_analysis_job
from ip_risk_agent.application.process_change.models import ChangeEvent, ChangeEventStatus
from ip_risk_agent.application.process_change.transitions import (
    complete_change_event,
    fail_change_event,
)
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.audit import SourceAccessEvent
from ip_risk_agent.core.common import (
    DomainInvariantError,
    normalize_utc,
    require_non_empty,
    stable_key,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.workspaces import RiskWorkspace, RiskWorkspaceStatus

from .ignore import IgnorePolicyError, is_ignored, parse_ipriskignore
from .minimization import minimize_segments
from ip_risk_agent.core.artifacts.dependency_files import DEPENDENCY_KINDS
from ip_risk_agent.core.artifacts.text_files import (
    NON_COMMITTAL_MIME_TYPES,
    is_text_like,
)

from .policy import (
    SecurityGatePolicy,
    SecurityPolicyResolutionError,
    SecurityPolicyResolver,
    SourceScopeDecision,
)
from .redaction import redact_segments

Clock = Callable[[], datetime]


class SecurityGateDenialReason(StrEnum):
    CANONICAL_CONTEXT_MISMATCH = "CANONICAL_CONTEXT_MISMATCH"
    CANONICAL_CONTEXT_UNAVAILABLE = "CANONICAL_CONTEXT_UNAVAILABLE"
    INVALID_JOB_STATE = "INVALID_JOB_STATE"
    INVALID_SNAPSHOT = "INVALID_SNAPSHOT"
    STALE_REVISION = "STALE_REVISION"
    SOURCE_SCOPE_DENIED = "SOURCE_SCOPE_DENIED"
    GLOBAL_IGNORE_DENIED = "GLOBAL_IGNORE_DENIED"
    SOURCE_IGNORE_DENIED = "SOURCE_IGNORE_DENIED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    POLICY_INVALID = "POLICY_INVALID"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    FILE_TYPE_DENIED = "FILE_TYPE_DENIED"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    NO_ELIGIBLE_ANALYZER = "NO_ELIGIBLE_ANALYZER"


_FAILED_GATE_REASONS = frozenset(
    {
        SecurityGateDenialReason.CANONICAL_CONTEXT_MISMATCH,
        SecurityGateDenialReason.CANONICAL_CONTEXT_UNAVAILABLE,
        SecurityGateDenialReason.INVALID_SNAPSHOT,
        SecurityGateDenialReason.POLICY_INVALID,
        SecurityGateDenialReason.POLICY_UNAVAILABLE,
    }
)


@dataclass(frozen=True, slots=True)
class SecurityGateResult:
    analysis_artifact: AnalysisArtifact | None
    denial_reason: SecurityGateDenialReason | None
    source_access_event_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.source_access_event_id, "security_gate.source_access_event_id")
        if (self.analysis_artifact is None) == (self.denial_reason is None):
            raise DomainInvariantError(
                "SecurityGateResult requires exactly one artifact or denial reason"
            )

    @property
    def approved(self) -> bool:
        return self.analysis_artifact is not None


@dataclass(frozen=True, slots=True)
class _CanonicalContext:
    workspace: RiskWorkspace
    mount: WorkspaceMount
    source_workspace: SourceWorkspace
    source_connection: SourceConnection
    artifact: Artifact
    artifact_state: ArtifactState
    change_event: ChangeEvent
    analysis_job: AnalysisJob


class SecurityGateService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        policy_resolver: SecurityPolicyResolver,
        clock: Clock,
        concurrency_attempts: int = 3,
        use_canonical_workspace_policy_text: bool = False,
    ) -> None:
        if concurrency_attempts < 1:
            raise ValueError("concurrency_attempts must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._policy_resolver = policy_resolver
        self._clock = clock
        self._concurrency_attempts = concurrency_attempts
        self._use_canonical_workspace_policy_text = (
            use_canonical_workspace_policy_text
        )

    async def build_analysis_artifact(
        self,
        snapshot: SourceSnapshot,
        analysis_job_id: str,
        *,
        source_scope: SourceScopeDecision | None = None,
    ) -> SecurityGateResult:
        source_scope = source_scope or SourceScopeDecision()
        last_conflict: ConcurrencyConflictError | None = None
        for _ in range(self._concurrency_attempts):
            try:
                return await self._build_once(snapshot, analysis_job_id, source_scope)
            except ConcurrencyConflictError as exc:
                last_conflict = exc
        assert last_conflict is not None
        raise last_conflict

    async def _build_once(
        self,
        snapshot: SourceSnapshot,
        analysis_job_id: str,
        source_scope: SourceScopeDecision,
    ) -> SecurityGateResult:
        async with self._unit_of_work_factory() as uow:
            context = await _load_context(uow, analysis_job_id)
            access_event = _source_access_event(context, snapshot)
            await _append_source_access_idempotently(uow, access_event)

            reason = _persisted_denial_reason(context)
            if reason is None:
                reason = _validate_context(context, snapshot)
            analysis_artifact = None
            if reason is None:
                reason, analysis_artifact = self._apply_policy(
                    context,
                    snapshot,
                    source_scope,
                )
                if analysis_artifact is not None:
                    routed_job = replace(
                        context.analysis_job,
                        requested_analysis_types=tuple(
                            analysis_artifact.requested_analyzers
                        ),
                        # 이 작업이 무엇을 보고 판단하는지를 여기서 남긴다 (§7.4 · 3-B).
                        # 계약이 동결이라 결과에 실어 되돌려 받을 수 없고, 애초에
                        # **입력의 성질**이므로 분석 전인 이 자리가 맞다.
                        analysis_input_checksum=(
                            analysis_artifact.security_context.analysis_input_checksum
                        ),
                    )
                    await uow.analysis_jobs.save(routed_job)
                state = replace(
                    context.artifact_state,
                    latest_checksum=require_non_empty(
                        snapshot.checksum, "source_snapshot.checksum"
                    ),
                    updated_at=max(
                        context.artifact_state.updated_at,
                        normalize_utc(
                            snapshot.source_access_receipt.occurred_at,
                            "source_access_receipt.occurred_at",
                        ),
                    ),
                )
                await uow.artifacts.save_state(state)
            if reason is not None:
                await self._finalize_denied_job(uow, context, reason)

            await uow.commit()

        return SecurityGateResult(
            analysis_artifact=analysis_artifact,
            denial_reason=reason,
            source_access_event_id=access_event.id,
        )

    def _apply_policy(
        self,
        context: _CanonicalContext,
        snapshot: SourceSnapshot,
        source_scope: SourceScopeDecision,
    ) -> tuple[SecurityGateDenialReason | None, AnalysisArtifact | None]:
        if not source_scope.in_scope:
            return SecurityGateDenialReason.SOURCE_SCOPE_DENIED, None
        try:
            policy = self._policy_resolver.resolve(
                context.workspace.id,
                context.workspace.security_policy_version,
            )
        except SecurityPolicyResolutionError:
            return SecurityGateDenialReason.POLICY_UNAVAILABLE, None
        if policy.policy_version != context.workspace.security_policy_version:
            return SecurityGateDenialReason.POLICY_INVALID, None
        if self._use_canonical_workspace_policy_text:
            policy = replace(
                policy,
                global_ignore_text=context.workspace.global_ignore_text,
            )

        logical_path = _canonical_logical_path(context.artifact.logical_path)
        try:
            if is_ignored(logical_path, parse_ipriskignore(policy.global_ignore_text)):
                return SecurityGateDenialReason.GLOBAL_IGNORE_DENIED, None
            if is_ignored(logical_path, parse_ipriskignore(source_scope.ignore_text)):
                return SecurityGateDenialReason.SOURCE_IGNORE_DENIED, None
        except IgnorePolicyError:
            return SecurityGateDenialReason.POLICY_INVALID, None

        if snapshot.content_scope in {
            ContentScope.METADATA_ONLY,
            ContentScope.UNSUPPORTED,
        } or not snapshot.text_segments:
            return SecurityGateDenialReason.UNSUPPORTED_CONTENT, None
        if _mime_is_denied(
            snapshot.mime_type,
            snapshot.artifact_kind,
            policy,
            # 이름이 유일한 단서다. 경로 힌트가 있으면 그것을, 없으면 표시
            # 이름을 본다 — 확장자만 보므로 둘 중 무엇이든 답은 같다.
            logical_path=snapshot.logical_path_hint or snapshot.display_name,
        ):
            return SecurityGateDenialReason.FILE_TYPE_DENIED, None
        input_bytes = max(
            snapshot.byte_size,
            snapshot.source_access_receipt.content_bytes,
            sum(len(segment.text.encode("utf-8")) for segment in snapshot.text_segments),
        )
        if input_bytes > policy.max_input_bytes:
            return SecurityGateDenialReason.CONTENT_TOO_LARGE, None

        redacted, redaction_count = redact_segments(
            snapshot.text_segments,
            # 매니페스트의 왼쪽은 설정 키가 아니라 패키지 이름이다. 낱말로 찾는 패턴은
            # 거기서 이름을 비밀로 오인해 선언을 망가뜨린다.
            keyword_patterns=snapshot.artifact_kind not in DEPENDENCY_KINDS,
        )
        minimized, content_scope = minimize_segments(
            artifact_kind=snapshot.artifact_kind,
            content_scope=snapshot.content_scope,
            segments=redacted,
            source_byte_size=input_bytes,
            policy=policy,
        )
        if not minimized or not any(segment.text for segment in minimized):
            return SecurityGateDenialReason.UNSUPPORTED_CONTENT, None
        requested_analyzers = _eligible_analyzers(
            snapshot.artifact_kind,
            context.analysis_job.requested_analysis_types,
            policy,
        )
        if not requested_analyzers:
            return SecurityGateDenialReason.NO_ELIGIBLE_ANALYZER, None

        checksum = _analysis_input_checksum(
            artifact_id=context.artifact.id,
            revision=context.analysis_job.revision,
            artifact_kind=snapshot.artifact_kind,
            mime_type=snapshot.mime_type,
            analyzers=requested_analyzers,
            content_scope=content_scope,
            segments=minimized,
        )
        artifact = AnalysisArtifact(
            contract_version="1",
            analysis_job_id=context.analysis_job.id,
            risk_workspace_id=context.workspace.id,
            mount_id=context.mount.id,
            artifact_id=context.artifact.id,
            logical_path=logical_path,
            revision=context.analysis_job.revision,
            artifact_kind=snapshot.artifact_kind,
            mime_type=snapshot.mime_type,
            requested_analyzers=list(requested_analyzers),
            content_scope=content_scope,
            text_segments=minimized,
            security_context=AnalysisSecurityContext(
                approved=True,
                policy_version=policy.policy_version,
                redaction_count=redaction_count,
                original_checksum=snapshot.checksum,
                analysis_input_checksum=checksum,
            ),
            created_at=normalize_utc(self._clock(), "security_gate.clock"),
        ).require_approved()
        return None, artifact

    async def _finalize_denied_job(
        self,
        uow: ControlUnitOfWork,
        context: _CanonicalContext,
        reason: SecurityGateDenialReason,
    ) -> None:
        if (
            context.analysis_job.status is not AnalysisJobStatus.RUNNING
            or context.change_event.status is not ChangeEventStatus.PROCESSING
        ):
            return
        occurred_at = normalize_utc(self._clock(), "security_gate.denial_clock")
        failure_safe = f"SECURITY_GATE:{reason.value}"
        if reason in _FAILED_GATE_REASONS:
            job = complete_analysis_job(
                context.analysis_job,
                status=AnalysisJobStatus.FAILED,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            )
            event = fail_change_event(
                context.change_event,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            )
        else:
            job = complete_analysis_job(
                context.analysis_job,
                status=AnalysisJobStatus.INCONCLUSIVE,
                occurred_at=occurred_at,
                failure_safe=failure_safe,
            )
            event = complete_change_event(
                context.change_event,
                occurred_at=occurred_at,
            )
        await uow.analysis_jobs.save(job)
        await uow.change_events.save(event)


async def _load_context(
    uow: ControlUnitOfWork, analysis_job_id: str
) -> _CanonicalContext:
    analysis_job = await uow.analysis_jobs.get(analysis_job_id)
    if analysis_job is None:
        raise RecordNotFoundError(f"analysis job was not found: {analysis_job_id!r}")
    change_event = await uow.change_events.get(analysis_job.change_event_id)
    artifact = await uow.artifacts.get(analysis_job.artifact_id)
    artifact_state = await uow.artifacts.get_state(analysis_job.artifact_id)
    if change_event is None or artifact is None or artifact_state is None:
        raise RecordNotFoundError("analysis job canonical context is incomplete")
    mount = await uow.mounts.get(artifact.mount_id)
    source_workspace = await uow.source_metadata.get_source_workspace(
        artifact.source_workspace_id
    )
    workspace = await uow.workspaces.get(artifact.risk_workspace_id)
    if mount is None or source_workspace is None or workspace is None:
        raise RecordNotFoundError("artifact canonical source context is incomplete")
    source_connection = await uow.source_metadata.get_connection(
        source_workspace.source_connection_id
    )
    if source_connection is None:
        raise RecordNotFoundError("artifact source connection was not found")
    return _CanonicalContext(
        workspace,
        mount,
        source_workspace,
        source_connection,
        artifact,
        artifact_state,
        change_event,
        analysis_job,
    )


def _validate_context(
    context: _CanonicalContext, snapshot: SourceSnapshot
) -> SecurityGateDenialReason | None:
    job = context.analysis_job
    event = context.change_event
    artifact = context.artifact
    state = context.artifact_state
    mount = context.mount
    source_workspace = context.source_workspace
    connection = context.source_connection
    workspace = context.workspace
    if (
        job.status is not AnalysisJobStatus.RUNNING
        or event.status is not ChangeEventStatus.PROCESSING
    ):
        return SecurityGateDenialReason.INVALID_JOB_STATE
    if (
        event.id != job.change_event_id
        or event.artifact_id != artifact.id
        or job.artifact_id != artifact.id
        or state.artifact_id != artifact.id
        or artifact.risk_workspace_id != workspace.id
        or artifact.mount_id != mount.id
        or artifact.source_workspace_id != source_workspace.id
        or mount.risk_workspace_id != workspace.id
        or mount.source_workspace_id != source_workspace.id
        or mount.source_connection_id != source_workspace.source_connection_id
        or source_workspace.source_connection_id != connection.id
        or artifact.source_type is not source_workspace.source_type
        or source_workspace.source_type is not connection.provider
    ):
        return SecurityGateDenialReason.CANONICAL_CONTEXT_MISMATCH
    if (
        workspace.status is not RiskWorkspaceStatus.ACTIVE
        or mount.status is not MountStatus.ACTIVE
        or source_workspace.status is not SourceWorkspaceStatus.ACTIVE
        or connection.status is not SourceConnectionStatus.ACTIVE
        or artifact.status is not ArtifactStatus.ACTIVE
        or state.availability_state is not ArtifactAvailability.AVAILABLE
    ):
        return SecurityGateDenialReason.CANONICAL_CONTEXT_UNAVAILABLE
    if (
        snapshot.risk_workspace_id != workspace.id
        or snapshot.mount_id != mount.id
        or snapshot.source_workspace_id != source_workspace.id
        or snapshot.source_type is not artifact.source_type
        or snapshot.source_artifact_id != artifact.source_artifact_id
        or snapshot.display_name != artifact.display_name
    ):
        return SecurityGateDenialReason.CANONICAL_CONTEXT_MISMATCH
    if (
        snapshot.resolved_revision != job.revision
        or event.revision != job.revision
        or state.latest_revision != job.revision
    ):
        return SecurityGateDenialReason.STALE_REVISION
    if not snapshot.checksum.strip():
        return SecurityGateDenialReason.INVALID_SNAPSHOT
    segment_ids = [segment.segment_id.strip() for segment in snapshot.text_segments]
    if any(not segment_id for segment_id in segment_ids) or len(segment_ids) != len(
        set(segment_ids)
    ):
        return SecurityGateDenialReason.INVALID_SNAPSHOT
    if snapshot.logical_path_hint is not None:
        try:
            expected = _logical_path_from_hint(mount.alias, snapshot.logical_path_hint)
        except DomainInvariantError:
            return SecurityGateDenialReason.INVALID_SNAPSHOT
        if expected != artifact.logical_path:
            return SecurityGateDenialReason.CANONICAL_CONTEXT_MISMATCH
    return None


def _persisted_denial_reason(
    context: _CanonicalContext,
) -> SecurityGateDenialReason | None:
    job = context.analysis_job
    event = context.change_event
    is_gate_terminal = (
        event.status is ChangeEventStatus.DONE
        and job.status is AnalysisJobStatus.INCONCLUSIVE
    ) or (
        event.status is ChangeEventStatus.FAILED
        and job.status is AnalysisJobStatus.FAILED
    )
    prefix = "SECURITY_GATE:"
    if not is_gate_terminal or not job.failure_safe or not job.failure_safe.startswith(prefix):
        return None
    try:
        return SecurityGateDenialReason(job.failure_safe.removeprefix(prefix))
    except ValueError:
        return None


def _logical_path_from_hint(alias: str, path_hint: str) -> str:
    relative = require_non_empty(path_hint, "source_snapshot.logical_path_hint")
    if "\\" in relative or relative.startswith("/") or re.match(r"^[A-Za-z]:", relative):
        raise DomainInvariantError("snapshot path must be provider-relative")
    path = PurePosixPath(relative)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise DomainInvariantError("snapshot path contains invalid traversal")
    return f"{alias}/{'/'.join(path.parts)}"


def _canonical_logical_path(value: str) -> str:
    path = "/" + require_non_empty(value, "artifact.logical_path").strip("/")
    if "\\" in path or "//" in path:
        raise DomainInvariantError("artifact logical path is not canonical")
    if any(part in {"", ".", ".."} for part in path.split("/")[1:]):
        raise DomainInvariantError("artifact logical path contains invalid traversal")
    return path


def _mime_is_denied(
    mime_type: str | None,
    artifact_kind: ArtifactKind,
    policy: SecurityGatePolicy,
    *,
    logical_path: str = "",
) -> bool:
    if mime_type is None:
        return False
    normalized = mime_type.split(";", 1)[0].strip().casefold()
    if normalized in NON_COMMITTAL_MIME_TYPES and is_text_like(logical_path):
        # 이 mime 은 "이것이 무엇인지 말하지 않겠다" 는 뜻이다. 그럴 때는 이름이
        # 유일한 단서다.
        #
        # Drive 가 `.md` 를 `application/octet-stream` 으로 넘기는 일이 있고, 그것이
        # 여기서 막혔다. GitHub 과 Local 은 mime 을 아예 넘기지 않아(`None`) 위에서
        # 그냥 통과하므로 같은 파일이 **소스마다 다른 판정**을 받았다.
        #
        # 이름이 틀렸으면 내용이 잡는다. 확장자는 텍스트인데 알맹이가 바이너리면
        # UTF-8 디코드가 실패하고, 그것이 정직한 "미지원" 이다 (§6.2).
        #
        # **적극적으로 무엇이라고 말하는 mime 은 뒤집지 않는다.** `image/png` 은
        # 판단을 미룬 것이 아니라 이미지라고 주장하는 것이다. 그것을 파일 이름
        # 추측으로 덮으면 확장자만 바꿔 게이트를 지나갈 수 있게 된다.
        return False
    if normalized in policy.denied_mime_types or any(
        normalized.startswith(prefix) for prefix in policy.denied_mime_prefixes
    ):
        return True

    if normalized.startswith("text/"):
        return False
    textual_application_types = {
        "application/ecmascript",
        "application/javascript",
        "application/json",
        "application/ld+json",
        "application/toml",
        "application/x-httpd-php",
        "application/x-javascript",
        "application/x-sh",
        "application/x-yaml",
        "application/xml",
        "application/yaml",
    }
    if normalized in textual_application_types:
        return False
    document_types = {
        "application/msword",
        "application/pdf",
        "application/rtf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        # Google Docs 는 어댑터가 text/plain 으로 export 해서 넘긴다. 그런데
        # snapshot 의 mime 은 원본 형식 그대로라, 여기서 받아 주지 않으면 이미
        # 텍스트로 읽어 온 문서를 FILE_TYPE_DENIED 로 막는다. 운영에서 실제로
        # Google 문서 하나가 그렇게 막혔다.
        #
        # Sheets/Slides 는 넣지 않는다. `read_text` 가 export 하는 것은 Docs 뿐이고,
        # 다루지 못하는 형식을 통과시키면 더 뒤에서 알 수 없는 실패가 된다.
        "application/vnd.google-apps.document",
    }
    return not (
        artifact_kind is ArtifactKind.DOCUMENT_TEXT and normalized in document_types
    )


def _eligible_analyzers(
    artifact_kind: ArtifactKind,
    requested: tuple[AnalysisType, ...],
    policy: SecurityGatePolicy,
) -> tuple[AnalysisType, ...]:
    matrix: dict[ArtifactKind, tuple[AnalysisType, ...]] = {
        ArtifactKind.MANIFEST: (AnalysisType.LICENSE,),
        ArtifactKind.LOCKFILE: (AnalysisType.LICENSE,),
        ArtifactKind.SOURCE_CODE: (AnalysisType.PATENT,),
        ArtifactKind.DOCUMENT_TEXT: (AnalysisType.PATENT,),
        ArtifactKind.TEXT: (
            (AnalysisType.PATENT,) if policy.allow_text_patent else ()
        ),
        ArtifactKind.UNKNOWN: (),
    }
    requested_set = set(requested)
    return tuple(item for item in matrix[artifact_kind] if item in requested_set)


def _analysis_input_checksum(
    *,
    artifact_id: str,
    revision: str,
    artifact_kind: ArtifactKind,
    mime_type: str | None,
    analyzers: tuple[AnalysisType, ...],
    content_scope: ContentScope,
    segments: list[TextSegment],
) -> str:
    payload = {
        "artifact_id": artifact_id,
        "revision": revision,
        "artifact_kind": artifact_kind.value,
        "mime_type": mime_type,
        "requested_analyzers": [item.value for item in analyzers],
        "content_scope": content_scope.value,
        "text_segments": [segment.model_dump(mode="json") for segment in segments],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(serialized).hexdigest()}"


def _source_access_event(
    context: _CanonicalContext, snapshot: SourceSnapshot
) -> SourceAccessEvent:
    receipt = snapshot.source_access_receipt
    accessed_revision = snapshot.resolved_revision.strip() or "<invalid-revision>"
    provider_component = (
        "<none>"
        if receipt.provider_request_id is None
        else receipt.provider_request_id or "<empty>"
    )
    occurred_at = normalize_utc(receipt.occurred_at, "source_access_receipt.occurred_at")
    event_id = stable_key(
        "source-access",
        (
            context.analysis_job.id,
            accessed_revision,
            receipt.access_type.value,
            provider_component,
            occurred_at.isoformat(),
            str(receipt.content_bytes),
        ),
    )
    return SourceAccessEvent(
        id=event_id,
        risk_workspace_id=context.workspace.id,
        mount_id=context.mount.id,
        artifact_id=context.artifact.id,
        access_type=receipt.access_type,
        revision=accessed_revision,
        content_bytes=receipt.content_bytes,
        occurred_at=occurred_at,
        analysis_job_id=context.analysis_job.id,
        provider_request_id=receipt.provider_request_id,
    )


async def _append_source_access_idempotently(
    uow: ControlUnitOfWork, event: SourceAccessEvent
) -> None:
    existing = await uow.audit.get_source_access(event.id)
    if existing is None:
        await uow.audit.append_source_access(event)
    elif existing != event:
        raise DomainInvariantError("source access event identity collision")


__all__ = [
    "SecurityGateDenialReason",
    "SecurityGateResult",
    "SecurityGateService",
]
