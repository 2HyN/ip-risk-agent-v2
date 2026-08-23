from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts import (
    AnalysisType,
    ArtifactKind,
    ChangeType,
    ContentScope,
    SegmentKind,
    SourceAccessReceipt,
    SourceAccessType,
    SourceArtifactRef,
    SourceChange,
    SourceSnapshot,
    SourceType,
    TextSegment,
)
from ip_risk_agent.application.analysis_jobs.service import AnalysisJobOrchestrationService
from ip_risk_agent.application.analysis_jobs import AnalysisJobStatus
from ip_risk_agent.application.process_change import ChangeEventStatus, InMemoryTaskEnqueuer
from ip_risk_agent.application.process_change.service import SourceChangeIntakeService
from ip_risk_agent.application.repositories import (
    InMemoryControlStore,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.security_gate import (
    IgnorePolicyError,
    InMemorySecurityPolicyResolver,
    REDACTION_PLACEHOLDER,
    SecurityGateDenialReason,
    SecurityGatePolicy,
    SecurityGateService,
    SourceScopeDecision,
    is_ignored,
    parse_ipriskignore,
    redact_text,
)
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 18, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


async def seed_running_job(
    *,
    path_hint: str = "src/main.py",
    source_artifact_id: str = "repo:path:src/main.py",
) -> tuple[InMemoryControlStore, InMemoryTaskEnqueuer, str, str]:
    store = InMemoryControlStore()
    queue = InMemoryTaskEnqueuer()
    async with store() as uow:
        await uow.workspaces.add(
            RiskWorkspace(
                "vws-1",
                "Workspace",
                "owner-1",
                "security-v1",
                "retention-v1",
                NOW,
                NOW,
            )
        )
        await uow.source_metadata.add_connection(
            SourceConnection(
                "connection-1",
                SourceType.GITHUB,
                "manager-1",
                SourceConnectionStatus.ACTIVE,
                NOW,
                NOW,
            )
        )
        await uow.source_metadata.add_source_workspace(
            SourceWorkspace(
                "source-1",
                "connection-1",
                SourceType.GITHUB,
                "repo-42",
                "org/repo",
                SourceWorkspaceStatus.ACTIVE,
                NOW,
                NOW,
            )
        )
        await uow.mounts.add(
            WorkspaceMount(
                "mount-1",
                "vws-1",
                "source-1",
                "Backend",
                "manager-1",
                "connection-1",
                MountStatus.ACTIVE,
                NOW,
                NOW,
            )
        )
        await uow.commit()

    intake = SourceChangeIntakeService(
        unit_of_work_factory=store,
        task_enqueuer=queue,
        clock=lambda: NOW,
    )
    registration = await intake.register_source_change(
        SourceChange(
            contract_version="1",
            event_id="source-event-1",
            provider_event_id="provider-event-1",
            event_fingerprint="fingerprint-1",
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            source_workspace_id="source-1",
            source_type=SourceType.GITHUB,
            artifact=SourceArtifactRef(
                source_artifact_id=source_artifact_id,
                display_name=path_hint.rsplit("/", 1)[-1],
                path_hint=path_hint,
            ),
            change_type=ChangeType.CREATE,
            revision="revision-1",
            observed_at=NOW,
            safe_metadata={},
        )
    )
    jobs = AnalysisJobOrchestrationService(
        unit_of_work_factory=store,
        task_enqueuer=queue,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    assert await jobs.claim(registration.change_event_id) is not None
    assert registration.analysis_job_id is not None
    return store, queue, registration.analysis_job_id, registration.artifact_id


def make_snapshot(
    *,
    path_hint: str = "src/main.py",
    source_artifact_id: str = "repo:path:src/main.py",
    artifact_kind: ArtifactKind = ArtifactKind.SOURCE_CODE,
    content_scope: ContentScope = ContentScope.FULL_TEXT,
    mime_type: str | None = "text/x-python",
    byte_size: int = 500,
    revision: str = "revision-1",
    mount_id: str = "mount-1",
    segments: list[TextSegment] | None = None,
) -> SourceSnapshot:
    return SourceSnapshot(
        contract_version="1",
        risk_workspace_id="vws-1",
        mount_id=mount_id,
        source_workspace_id="source-1",
        source_type=SourceType.GITHUB,
        source_artifact_id=source_artifact_id,
        resolved_revision=revision,
        retrieved_at=NOW + timedelta(seconds=2),
        display_name=path_hint.rsplit("/", 1)[-1],
        logical_path_hint=path_hint,
        mime_type=mime_type,
        artifact_kind=artifact_kind,
        content_scope=content_scope,
        text_segments=segments
        if segments is not None
        else [
            TextSegment(
                segment_id="changed-1",
                text="def main(): return True",
                line_start=1,
                line_end=1,
                segment_kind=SegmentKind.CHANGED,
            )
        ],
        checksum="sha256:original-revision-1",
        byte_size=byte_size,
        source_access_receipt=SourceAccessReceipt(
            access_type=SourceAccessType.FULL_CONTENT,
            provider_request_id="provider-request-1",
            content_bytes=byte_size,
            occurred_at=NOW + timedelta(seconds=2),
        ),
    )


def make_gate(
    store: InMemoryControlStore,
    policy: SecurityGatePolicy | None = None,
) -> SecurityGateService:
    policy = policy or SecurityGatePolicy(policy_version="security-v1")
    return SecurityGateService(
        unit_of_work_factory=store,
        policy_resolver=InMemorySecurityPolicyResolver((("vws-1", policy),)),
        clock=lambda: NOW + timedelta(seconds=3),
    )


def test_ipriskignore_is_deny_only_mount_absolute_and_case_conservative() -> None:
    rules = parse_ipriskignore(
        """
        # secrets
        /backend/**/.env*
        /backend/**/secrets/**
        /design/private-hr/?ata.txt
        """
    )
    assert is_ignored("/Backend/.env", rules)
    assert is_ignored("/backend/app/.env.production", rules)
    assert is_ignored("/backend/app/secrets/token.txt", rules)
    assert is_ignored("/design/private-hr/data.txt", rules)
    assert not is_ignored("/backend/src/main.py", rules)
    with pytest.raises(IgnorePolicyError, match="negation"):
        parse_ipriskignore("!/backend/public/**")
    with pytest.raises(IgnorePolicyError, match="mount-absolute"):
        parse_ipriskignore("backend/private/**")


def test_secret_redaction_is_deterministic_and_counts_each_match() -> None:
    source = """API_KEY=plain-secret
normal=value
-----BEGIN PRIVATE KEY-----
private-material
-----END PRIVATE KEY-----
header = 'Bearer abcdefghijklmnop'
github_pat_abcdefghijklmnopqrstuvwxyz
"""
    first, count = redact_text(source)
    second, second_count = redact_text(source)
    assert first == second
    assert count == second_count == 4
    assert redact_text(first) == (first, 0)
    assert first.count(REDACTION_PLACEHOLDER) == 4
    for secret in (
        "plain-secret",
        "private-material",
        "abcdefghijklmnop",
        "github_pat_abcdefghijklmnopqrstuvwxyz",
    ):
        assert secret not in first


def test_gate_approves_minimized_redacted_input_and_records_access_once() -> None:
    async def scenario() -> None:
        store, _, job_id, artifact_id = await seed_running_job()
        gate = make_gate(store)
        snapshot = make_snapshot(
            segments=[
                TextSegment(
                    segment_id="full-1",
                    text="entire old file",
                    segment_kind=SegmentKind.FULL,
                ),
                TextSegment(
                    segment_id="changed-1",
                    text="API_KEY=secret-value\ndef changed(): return True",
                    line_start=10,
                    line_end=11,
                    segment_kind=SegmentKind.CHANGED,
                ),
                TextSegment(
                    segment_id="context-1",
                    text="def context(): return False",
                    line_start=12,
                    line_end=12,
                    segment_kind=SegmentKind.CONTEXT,
                ),
            ]
        )
        first = await gate.build_analysis_artifact(snapshot, job_id)
        second = await gate.build_analysis_artifact(snapshot, job_id)
        assert first.approved and second.approved
        artifact = first.analysis_artifact
        assert artifact is not None
        assert artifact.artifact_id == artifact_id
        assert artifact.logical_path == "/Backend/src/main.py"
        assert artifact.requested_analyzers == [AnalysisType.PATENT]
        assert artifact.content_scope is ContentScope.CHANGESET_WITH_CONTEXT
        assert [segment.segment_id for segment in artifact.text_segments] == [
            "changed-1",
            "context-1",
        ]
        assert artifact.security_context.redaction_count == 1
        assert REDACTION_PLACEHOLDER in artifact.text_segments[0].text
        assert "secret-value" not in artifact.model_dump_json()
        assert (
            artifact.security_context.analysis_input_checksum
            == second.analysis_artifact.security_context.analysis_input_checksum
        )
        async with store() as uow:
            access = await uow.audit.list_source_access("vws-1")
            state = await uow.artifacts.get_state(artifact_id)
            job = await uow.analysis_jobs.get(job_id)
            assert len(access) == 1
            assert access[0].id == first.source_access_event_id
            assert access[0].analysis_job_id == job_id
            assert state is not None
            assert state.latest_checksum == snapshot.checksum
            assert job is not None and job.status is AnalysisJobStatus.RUNNING
            assert job.requested_analysis_types == (AnalysisType.PATENT,)
            with pytest.raises(UniqueConstraintViolation, match="only be narrowed"):
                await uow.analysis_jobs.save(
                    replace(
                        job,
                        requested_analysis_types=(
                            AnalysisType.LICENSE,
                            AnalysisType.PATENT,
                        ),
                    )
                )

    run(scenario())


@pytest.mark.parametrize(
    ("global_ignore", "source_scope", "expected"),
    (
        (
            "/backend/**/.env*",
            SourceScopeDecision(),
            SecurityGateDenialReason.GLOBAL_IGNORE_DENIED,
        ),
        (
            "",
            SourceScopeDecision(ignore_text="/backend/**/.env*"),
            SecurityGateDenialReason.SOURCE_IGNORE_DENIED,
        ),
        (
            "",
            SourceScopeDecision(in_scope=False, denial_code_safe="OUTSIDE_BRANCH"),
            SecurityGateDenialReason.SOURCE_SCOPE_DENIED,
        ),
    ),
)
def test_every_global_or_source_scope_deny_wins_and_still_records_access(
    global_ignore: str,
    source_scope: SourceScopeDecision,
    expected: SecurityGateDenialReason,
) -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job(
            path_hint="config/.env.production",
            source_artifact_id="repo:path:config/.env.production",
        )
        gate = make_gate(
            store,
            SecurityGatePolicy(
                policy_version="security-v1",
                global_ignore_text=global_ignore,
            ),
        )
        result = await gate.build_analysis_artifact(
            make_snapshot(
                path_hint="config/.env.production",
                source_artifact_id="repo:path:config/.env.production",
            ),
            job_id,
            source_scope=source_scope,
        )
        assert not result.approved
        assert result.denial_reason is expected
        async with store() as uow:
            assert len(await uow.audit.list_source_access("vws-1")) == 1
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None and job.status is AnalysisJobStatus.INCONCLUSIVE

    run(scenario())


def test_canonical_workspace_policy_text_overrides_static_gate_template() -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job(
            path_hint="private/secret.py",
            source_artifact_id="repo:path:private/secret.py",
        )
        async with store() as uow:
            workspace = await uow.workspaces.get("vws-1")
            assert workspace is not None
            await uow.workspaces.save(
                replace(
                    workspace,
                    security_policy_version="security-v2",
                    global_ignore_text="/Backend/private/**\n",
                    updated_at=NOW + timedelta(seconds=1),
                )
            )
            await uow.commit()
        gate = SecurityGateService(
            unit_of_work_factory=store,
            policy_resolver=InMemorySecurityPolicyResolver(
                (("vws-1", SecurityGatePolicy(policy_version="security-v2")),)
            ),
            clock=lambda: NOW + timedelta(seconds=3),
            use_canonical_workspace_policy_text=True,
        )
        result = await gate.build_analysis_artifact(
            make_snapshot(
                path_hint="private/secret.py",
                source_artifact_id="repo:path:private/secret.py",
            ),
            job_id,
        )
        assert result.denial_reason is SecurityGateDenialReason.GLOBAL_IGNORE_DENIED

    run(scenario())


def test_invalid_ignore_policy_fails_closed_after_recording_access() -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job()
        gate = make_gate(
            store,
            SecurityGatePolicy(
                policy_version="security-v1",
                global_ignore_text="!/Backend/public/**",
            ),
        )
        result = await gate.build_analysis_artifact(make_snapshot(), job_id)
        assert result.denial_reason is SecurityGateDenialReason.POLICY_INVALID
        assert result.analysis_artifact is None
        async with store() as uow:
            assert await uow.audit.get_source_access(result.source_access_event_id) is not None
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None and job.status is AnalysisJobStatus.FAILED

    run(scenario())


@pytest.mark.parametrize(
    ("snapshot_kwargs", "policy", "expected"),
    (
        (
            {"mime_type": "image/png"},
            SecurityGatePolicy(policy_version="security-v1"),
            SecurityGateDenialReason.FILE_TYPE_DENIED,
        ),
        (
            {"mime_type": "application/x-msdownload"},
            SecurityGatePolicy(policy_version="security-v1"),
            SecurityGateDenialReason.FILE_TYPE_DENIED,
        ),
        (
            {"byte_size": 101},
            SecurityGatePolicy(
                policy_version="security-v1",
                max_input_bytes=100,
                max_output_bytes=100,
                max_segment_bytes=100,
                document_full_text_bytes=100,
            ),
            SecurityGateDenialReason.CONTENT_TOO_LARGE,
        ),
        (
            {"content_scope": ContentScope.METADATA_ONLY, "segments": []},
            SecurityGatePolicy(policy_version="security-v1"),
            SecurityGateDenialReason.UNSUPPORTED_CONTENT,
        ),
        (
            {"artifact_kind": ArtifactKind.UNKNOWN},
            SecurityGatePolicy(policy_version="security-v1"),
            SecurityGateDenialReason.NO_ELIGIBLE_ANALYZER,
        ),
        (
            {"artifact_kind": ArtifactKind.TEXT},
            SecurityGatePolicy(
                policy_version="security-v1",
                allow_text_patent=False,
            ),
            SecurityGateDenialReason.NO_ELIGIBLE_ANALYZER,
        ),
    ),
)
def test_type_size_scope_and_eligibility_denials_are_fail_closed(
    snapshot_kwargs: dict[str, object],
    policy: SecurityGatePolicy,
    expected: SecurityGateDenialReason,
) -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job()
        result = await make_gate(store, policy).build_analysis_artifact(
            make_snapshot(**snapshot_kwargs),
            job_id,
        )
        assert not result.approved
        assert result.denial_reason is expected
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None and job.status is AnalysisJobStatus.INCONCLUSIVE

    run(scenario())


@pytest.mark.parametrize(
    ("snapshot_kwargs", "expected"),
    (
        (
            {"mount_id": "different-mount"},
            SecurityGateDenialReason.CANONICAL_CONTEXT_MISMATCH,
        ),
        (
            {"revision": "stale-revision"},
            SecurityGateDenialReason.STALE_REVISION,
        ),
    ),
)
def test_context_or_revision_mismatch_never_creates_analysis_artifact(
    snapshot_kwargs: dict[str, object],
    expected: SecurityGateDenialReason,
) -> None:
    async def scenario() -> None:
        store, _, job_id, artifact_id = await seed_running_job()
        result = await make_gate(store).build_analysis_artifact(
            make_snapshot(**snapshot_kwargs),
            job_id,
        )
        assert result.analysis_artifact is None
        assert result.denial_reason is expected
        async with store() as uow:
            state = await uow.artifacts.get_state(artifact_id)
            job = await uow.analysis_jobs.get(job_id)
            event = await uow.change_events.get(job.change_event_id) if job else None
            assert state is not None and state.latest_checksum is None
            assert len(await uow.audit.list_source_access("vws-1")) == 1
            assert job is not None
            if expected is SecurityGateDenialReason.STALE_REVISION:
                assert job.status is AnalysisJobStatus.INCONCLUSIVE
                assert event is not None and event.status is ChangeEventStatus.DONE
            else:
                assert job.status is AnalysisJobStatus.FAILED
                assert event is not None and event.status is ChangeEventStatus.FAILED
            access = await uow.audit.get_source_access(result.source_access_event_id)
            assert access is not None
            assert access.revision == snapshot_kwargs.get("revision", "revision-1")

    run(scenario())


def test_manifest_routes_only_to_license_analyzer() -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job(
            path_hint="package.json",
            source_artifact_id="repo:path:package.json",
        )
        result = await make_gate(store).build_analysis_artifact(
            make_snapshot(
                path_hint="package.json",
                source_artifact_id="repo:path:package.json",
                artifact_kind=ArtifactKind.MANIFEST,
                mime_type="application/json",
            ),
            job_id,
        )
        assert result.analysis_artifact is not None
        assert result.analysis_artifact.requested_analyzers == [AnalysisType.LICENSE]
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None
            assert job.requested_analysis_types == (AnalysisType.LICENSE,)

    run(scenario())


def test_minimization_applies_exact_utf8_byte_caps_without_broken_text() -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job()
        policy = SecurityGatePolicy(
            policy_version="security-v1",
            max_input_bytes=100,
            max_output_bytes=6,
            max_segment_bytes=6,
            document_full_text_bytes=1,
        )
        result = await make_gate(store, policy).build_analysis_artifact(
            make_snapshot(
                artifact_kind=ArtifactKind.TEXT,
                byte_size=21,
                segments=[
                    TextSegment(
                        segment_id="full-1",
                        text="가나다라마바사",
                        segment_kind=SegmentKind.FULL,
                    )
                ],
            ),
            job_id,
        )
        assert result.analysis_artifact is not None
        assert result.analysis_artifact.text_segments[0].text == "가나"
        assert result.analysis_artifact.content_scope is ContentScope.CHANGESET_WITH_CONTEXT

    run(scenario())


def test_missing_policy_is_retryable_failed_state_and_idempotent_on_redelivery() -> None:
    async def scenario() -> None:
        store, _, job_id, _ = await seed_running_job()
        gate = SecurityGateService(
            unit_of_work_factory=store,
            policy_resolver=InMemorySecurityPolicyResolver(()),
            clock=lambda: NOW + timedelta(seconds=3),
        )
        snapshot = make_snapshot()
        first = await gate.build_analysis_artifact(snapshot, job_id)
        second = await gate.build_analysis_artifact(snapshot, job_id)
        assert first.denial_reason is SecurityGateDenialReason.POLICY_UNAVAILABLE
        assert second.denial_reason is first.denial_reason
        async with store() as uow:
            job = await uow.analysis_jobs.get(job_id)
            assert job is not None and job.status is AnalysisJobStatus.FAILED
            assert len(await uow.audit.list_source_access("vws-1")) == 1

    run(scenario())


# --------------------------------------------------------------------- 0-B


def test_a_package_name_is_not_mistaken_for_a_secret():
    """마스킹이 패키지 이름에 걸려 선언을 망가뜨렸다.

    ``tokenizers`` 는 HuggingFace 를 쓰는 거의 모든 프로젝트에 있고 ``secretstorage`` 는
    ``keyring`` 의 의존성이다. 드문 경우가 아니다.
    """
    from ip_risk_agent.application.security_gate.redaction import redact_text

    for line in ("tokenizers==0.15.0", "secretstorage==3.3.3"):
        assert redact_text(line, keyword_patterns=False)[0] == line
        # 설정 파일이었다면 가려지는 것이 맞다 — 끄는 것은 의존성 파일에서만이다.
        assert redact_text(line)[0] != line


def test_masking_a_manifest_leaves_it_parseable():
    """구조가 있는 형식은 따옴표 하나가 먹히면 **파일 전체가 0 건**이 된다."""
    from ip_risk_agent.application.security_gate.redaction import redact_text
    from ip_risk_agent.intelligence.license import manifests

    toml = (
        "[project]\n"
        'dependencies = ["httpx==0.28.1", "secret==1.0.0", "pydantic==2.13.4"]\n'
    )
    assert len(manifests.parse_pyproject_toml(toml, "pyproject.toml")) == 3

    safe = redact_text(toml, keyword_patterns=False)[0]
    assert len(manifests.parse_pyproject_toml(safe, "pyproject.toml")) == 3


def test_secrets_that_look_like_secrets_are_still_masked():
    """이름으로 찾는 것만 끈다. 생김새로 찾는 것은 의존성 파일에서도 돈다.

    의존성 명세에 자격증명이 박힌 URL 이 들어올 수 있다.
    """
    from ip_risk_agent.application.security_gate.redaction import (
        REDACTION_PLACEHOLDER,
        redact_text,
    )

    token = "ghp_" + "a" * 24
    masked, count = redact_text(
        f"pkg @ https://x.example/a.whl?token={token}", keyword_patterns=False
    )
    assert token not in masked
    assert REDACTION_PLACEHOLDER in masked
    assert count == 1

    bearer, _ = redact_text(
        "Authorization: Bearer abcdefghijklmnop", keyword_patterns=False
    )
    assert REDACTION_PLACEHOLDER in bearer
