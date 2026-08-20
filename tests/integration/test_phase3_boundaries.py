from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Request
from iprisk_contracts import (
    AnalysisArtifact,
    AnalysisCoverage,
    AnalysisResult,
    AnalysisSecurityContext,
    AnalysisStatus,
    AnalysisType,
    AnalysisVersions,
    ArtifactKind,
    ContentScope,
    MountRef,
    SegmentKind,
    SourceType,
    TextSegment,
)

from ip_risk_agent.api.common import CSRF_KEY, CurrentPrincipal
from ip_risk_agent.application.auth import AuthenticatedSession, AuthenticationError
from ip_risk_agent.application.public_facade import (
    FacadeAuthorizationDecision,
    PublicVwsAction,
    SourceMetadataRegistration,
)
from ip_risk_agent.composition.analyzer_completeness import (
    AnalyzerCompletenessError,
    CompleteIntelligenceFacade,
)
from ip_risk_agent.composition.device_auth import (
    DesktopDeviceAuthService,
    DeviceSourceAuthorizer,
    DeviceStatus,
    InMemoryDeviceAuthStore,
)
from ip_risk_agent.composition.source_auth import (
    ConnectionAccess,
    SessionSourceAuthorizer,
    SourceResourceScope,
)
from ip_risk_agent.composition.source_registration import (
    InMemoryPendingConnectionStore,
    PendingConnectionStatus,
    SourceRegistrationService,
)
from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.core.auth import User

NOW = datetime(2026, 8, 21, 3, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


class Clock:
    def __init__(self) -> None:
        self.current = NOW

    def __call__(self) -> datetime:
        return self.current


def principal(user_id: str = "owner-1", version: int = 3) -> CurrentPrincipal:
    return CurrentPrincipal(
        User(
            id=user_id,
            google_subject=f"subject-{user_id}",
            email=f"{user_id}@example.com",
            display_name=user_id,
            created_at=NOW,
            last_login_at=NOW,
            session_version=version,
        ),
        AuthenticatedSession(user_id, version),
    )


def request(
    method: str = "POST",
    *,
    headers: dict[str, str] | None = None,
    session: dict[str, object] | None = None,
) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": raw_headers,
            "session": session or {},
        }
    )


class FakePrincipalResolver:
    def __init__(self, value: CurrentPrincipal | None = None) -> None:
        self.value = value

    async def __call__(self, _request: Request) -> CurrentPrincipal:
        if self.value is None:
            raise AuthenticationError("missing")
        return self.value


class FakeControl:
    def __init__(self) -> None:
        self.auth_calls: list[dict[str, object]] = []
        self.registration_calls = []
        self.allowed = True

    async def authorize_vws_action(self, **values):
        self.auth_calls.append(values)
        return FacadeAuthorizationDecision(self.allowed, "ALLOWED", False)

    async def get_mount_ref(self, mount_id: str) -> MountRef:
        return MountRef(
            risk_workspace_id="vws-1",
            mount_id=mount_id,
            source_workspace_id="source-1",
            source_type=SourceType.GITHUB,
        )

    async def register_source_metadata(self, command):
        self.registration_calls.append(command)
        return SourceMetadataRegistration(
            connection_id="canonical-connection-1",
            source_workspace_id="canonical-source-1",
            mount_id="canonical-mount-1",
            created_connection=True,
            created_source_workspace=True,
            created_mount=True,
        )


class ConnectionResolver:
    def __init__(self, owner: str = "owner-1") -> None:
        self.owner = owner

    async def resolve_connection_access(self, _connection_id: str) -> ConnectionAccess:
        return ConnectionAccess("vws-1", self.owner)


def test_session_source_auth_is_scoped_csrf_protected_and_fail_closed() -> None:
    async def scenario() -> None:
        control = FakeControl()
        missing = SessionSourceAuthorizer(
            principal_resolver=FakePrincipalResolver(),
            control_facade=control,
            scope=SourceResourceScope.WORKSPACE,
        )
        with pytest.raises(HTTPException) as error:
            await missing(request(), "vws-1")
        assert error.value.status_code == 401

        workspace = SessionSourceAuthorizer(
            principal_resolver=FakePrincipalResolver(principal()),
            control_facade=control,
            scope=SourceResourceScope.WORKSPACE,
        )
        with pytest.raises(HTTPException) as error:
            await workspace(request(session={CSRF_KEY: "csrf"}), "vws-1")
        assert error.value.status_code == 403
        await workspace(
            request(headers={"X-CSRF-Token": "csrf"}, session={CSRF_KEY: "csrf"}),
            "vws-1",
        )
        assert control.auth_calls[-1]["action"] is PublicVwsAction.SOURCE_MOUNT

        connection = SessionSourceAuthorizer(
            principal_resolver=FakePrincipalResolver(principal()),
            control_facade=control,
            scope=SourceResourceScope.CONNECTION,
            connection_resolver=ConnectionResolver(owner="other-user"),
        )
        with pytest.raises(HTTPException) as error:
            await connection(request("GET"), "pending-1")
        assert error.value.status_code == 403

        mount = SessionSourceAuthorizer(
            principal_resolver=FakePrincipalResolver(principal()),
            control_facade=control,
            scope=SourceResourceScope.MOUNT,
        )
        await mount(request("GET"), "mount-1")
        assert control.auth_calls[-1]["action"] is PublicVwsAction.MOUNT_SOURCE_OPERATION
        assert control.auth_calls[-1]["mount_id"] == "mount-1"

    run(scenario())


def test_pending_connection_is_idempotent_and_mounts_only_after_selection() -> None:
    async def scenario() -> None:
        clock = Clock()
        store = InMemoryPendingConnectionStore()
        control = FakeControl()
        service = SourceRegistrationService(
            store=store,
            control_facade=control,
            principal_resolver=FakePrincipalResolver(principal()),
            clock=clock,
            ttl=timedelta(minutes=5),
        )
        credential = CredentialRef(
            provider=SourceType.GOOGLE_DRIVE,
            connection_id="oauth-state-1",
            secret_name="drive-oauth-token",
            key_id="secret-version-1",
        )
        first = await service.create_drive_connection(
            request("GET"),
            risk_workspace_id="vws-1",
            provider_subject="google-subject-1",
            provider_email="owner@example.com",
            credential_ref=credential,
        )
        second = await service.create_drive_connection(
            request("GET"),
            risk_workspace_id="vws-1",
            provider_subject="google-subject-1",
            provider_email="owner@example.com",
            credential_ref=credential,
        )
        assert first == second
        assert control.registration_calls == []
        result = await service.create_drive_mount(
            request(),
            connection_id=first,
            risk_workspace_id="vws-1",
            selected_file_ids=["file-2", "file-1"],
        )
        retried = await service.create_drive_mount(
            request(),
            connection_id=first,
            risk_workspace_id="vws-1",
            selected_file_ids=["file-1", "file-2"],
        )
        assert result == retried
        assert len(control.registration_calls) == 1
        command = control.registration_calls[0]
        assert command.external_scope_id != "pending"
        assert command.connection_key == "GOOGLE_DRIVE:google-subject-1"
        assert store.pending[first].status is PendingConnectionStatus.ACTIVE
        assert await service.resolve_credential_ref(first) == credential

        other_service = SourceRegistrationService(
            store=store,
            control_facade=control,
            principal_resolver=FakePrincipalResolver(principal("other-user")),
            clock=clock,
        )
        with pytest.raises(HTTPException) as error:
            await other_service.create_drive_mount(
                request(),
                connection_id=first,
                risk_workspace_id="vws-1",
                selected_file_ids=["file-3"],
            )
        assert error.value.status_code == 403

        github = await service.create_github_connection(
            request("GET"), risk_workspace_id="vws-1", installation_id="install-1"
        )
        clock.current += timedelta(minutes=6)
        with pytest.raises(HTTPException) as error:
            await service.resolve_installation_id(github)
        assert error.value.status_code == 410
        assert store.pending[github].status is PendingConnectionStatus.EXPIRED

    run(scenario())


def test_device_enrollment_is_one_time_hashed_bound_and_revocable() -> None:
    async def scenario() -> None:
        clock = Clock()
        store = InMemoryDeviceAuthStore()

        async def valid_session(user_id: str, version: int) -> bool:
            return user_id == "owner-1" and version == 3

        service = DesktopDeviceAuthService(
            store=store,
            session_version_validator=valid_session,
            clock=clock,
        )
        challenge = await service.issue_challenge(
            owner_user_id="owner-1", session_version=3
        )
        assert challenge not in repr(store.challenges)
        credential = await service.exchange_challenge(
            challenge=challenge,
            device_id="device-1",
            device_label="Developer laptop",
        )
        assert credential not in repr(store.devices)
        with pytest.raises(HTTPException) as error:
            await service.exchange_challenge(
                challenge=challenge,
                device_id="device-2",
                device_label="Replay",
            )
        assert error.value.status_code == 401

        authenticated = await service.authenticate(
            request(headers={"Authorization": f"Bearer {credential}"})
        )
        assert authenticated.device_id == "device-1"
        await service.bind_mount(
            device_id="device-1", risk_workspace_id="vws-1", mount_id="mount-1"
        )
        control = FakeControl()
        authorizer = DeviceSourceAuthorizer(devices=service, control_facade=control)
        await authorizer(
            request(headers={"Authorization": f"Bearer {credential}"}), "mount-1"
        )
        assert control.auth_calls[-1]["mount_id"] == "mount-1"
        with pytest.raises(HTTPException) as error:
            await authorizer(
                request(headers={"Authorization": f"Bearer {credential}"}), "mount-2"
            )
        assert error.value.status_code == 403

        await service.revoke("device-1")
        assert store.devices["device-1"].status is DeviceStatus.REVOKED
        with pytest.raises(HTTPException) as error:
            await service.authenticate(
                request(headers={"Authorization": f"Bearer {credential}"})
            )
        assert error.value.status_code == 401

    run(scenario())


def artifact() -> AnalysisArtifact:
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id="job-1",
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        artifact_id="artifact-1",
        logical_path="src/main.py",
        revision="revision-1",
        artifact_kind=ArtifactKind.SOURCE_CODE,
        mime_type="text/x-python",
        requested_analyzers=[AnalysisType.PATENT, AnalysisType.LICENSE],
        content_scope=ContentScope.FULL_TEXT,
        text_segments=[
            TextSegment(
                segment_id="segment-1",
                text="print('safe')",
                line_start=1,
                line_end=1,
                segment_kind=SegmentKind.FULL,
            )
        ],
        security_context=AnalysisSecurityContext(
            approved=True,
            policy_version="policy-v1",
            redaction_count=0,
            original_checksum="sha256:original",
            analysis_input_checksum="sha256:input",
        ),
        created_at=NOW,
    )


def result(analysis_type: AnalysisType) -> AnalysisResult:
    return AnalysisResult(
        contract_version="1",
        analysis_job_id="job-1",
        artifact_id="artifact-1",
        revision="revision-1",
        analysis_type=analysis_type,
        status=AnalysisStatus.SUCCEEDED,
        coverage=AnalysisCoverage.COMPLETE,
        candidates=[],
        evidence=[],
        provider_failures=[],
        versions=AnalysisVersions(analyzer_version="test-v1"),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )


@dataclass
class FakeIntelligence:
    results: list[AnalysisResult]

    async def analyze(self, _artifact: AnalysisArtifact) -> list[AnalysisResult]:
        return self.results


def test_analyzer_sets_and_result_identity_must_be_exact() -> None:
    expected = (AnalysisType.PATENT, AnalysisType.LICENSE)
    with pytest.raises(AnalyzerCompletenessError):
        CompleteIntelligenceFacade(
            FakeIntelligence([]),
            configured_analysis_types=expected,
            active_analysis_types=(AnalysisType.LICENSE,),
        )

    async def scenario() -> None:
        complete = CompleteIntelligenceFacade(
            FakeIntelligence([result(AnalysisType.PATENT), result(AnalysisType.LICENSE)]),
            configured_analysis_types=expected,
            active_analysis_types=expected,
        )
        assert len(await complete.analyze(artifact())) == 2

        for invalid in (
            [result(AnalysisType.PATENT)],
            [result(AnalysisType.PATENT), result(AnalysisType.PATENT)],
            [
                result(AnalysisType.PATENT),
                result(AnalysisType.LICENSE).model_copy(update={"artifact_id": "other"}),
            ],
        ):
            guarded = CompleteIntelligenceFacade(
                FakeIntelligence(invalid),
                configured_analysis_types=expected,
                active_analysis_types=expected,
            )
            with pytest.raises(AnalyzerCompletenessError):
                await guarded.analyze(artifact())

    run(scenario())
