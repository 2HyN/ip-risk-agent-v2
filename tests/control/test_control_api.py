from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import RedirectResponse

from iprisk_contracts import AnalysisType, ReviewPriority, SourceAccessType
from ip_risk_agent.api import (
    ApplicationHardeningConfig,
    ApplicationSessionConfig,
    ControlApiDependencies,
    create_control_api_bundle,
)
from ip_risk_agent.application.observability import StructuredLogger
from ip_risk_agent.api.auth import AuthRouterDependencies, GoogleOidcConfig
from ip_risk_agent.api.common import CursorCodec
from ip_risk_agent.api.history import HistoryRouterDependencies
from ip_risk_agent.api.notifications import NotificationRouterDependencies
from ip_risk_agent.api.risks import RiskRouterDependencies
from ip_risk_agent.api.security import SecurityRouterDependencies
from ip_risk_agent.api.workspaces import WorkspaceRouterDependencies
from ip_risk_agent.application.auth import (
    AuthenticatedSession,
    AuthenticationService,
    GoogleOidcIdentity,
)
from ip_risk_agent.application.history import HistoryQueryService
from ip_risk_agent.application.notifications import NotificationService
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.application.risk_review import RiskReviewService
from ip_risk_agent.application.security_policy import WorkspaceSecurityService
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.core.common import ActorType, DomainInvariantError
from ip_risk_agent.core.audit import SourceAccessEvent
from ip_risk_agent.core.notifications import (
    Notification,
    NotificationStatus,
    NotificationType,
)
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    MembershipInvitation,
    MembershipRole,
    invitation_id_for,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
SECRET = "phase-9-test-secret-that-is-at-least-32-characters"


@pytest.mark.parametrize("session_version", [True, "1", -1])
def test_authenticated_session_rejects_invalid_versions(session_version: object) -> None:
    with pytest.raises(DomainInvariantError, match="non-negative"):
        AuthenticatedSession("user-1", session_version)  # type: ignore[arg-type]


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, kind: str) -> str:
        self.value += 1
        return f"{kind}-{self.value}"


class FakeGoogleOidcClient:
    def __init__(self, identity: GoogleOidcIdentity) -> None:
        self.identity = identity
        self.callback_count = 0

    async def authorize_redirect(self, request: Request, redirect_uri: str):
        request.session["fake_oidc_state"] = "state-bound-to-signed-session"
        request.session["fake_oidc_nonce"] = "nonce-bound-to-signed-session"
        return RedirectResponse(
            "https://accounts.example.invalid/authorize?state=opaque"
        )

    async def fetch_identity(self, request: Request) -> GoogleOidcIdentity:
        assert request.session.pop("fake_oidc_state") == "state-bound-to-signed-session"
        assert request.session.pop("fake_oidc_nonce") == "nonce-bound-to-signed-session"
        self.callback_count += 1
        return self.identity


def build_api(
    identity: GoogleOidcIdentity | None = None,
    *,
    hardening: ApplicationHardeningConfig | None = None,
    observer: StructuredLogger | None = None,
):
    store = InMemoryControlStore()
    ids = SequentialIds()
    oidc = FakeGoogleOidcClient(
        identity
        or GoogleOidcIdentity(
            subject="google-subject-1",
            email="owner@example.com",
            email_verified=True,
            display_name="Owner",
            avatar_url="https://images.example.invalid/avatar?signed=secret",
        )
    )
    authentication = AuthenticationService(
        unit_of_work_factory=store,
        clock=lambda: NOW,
    )
    administration = WorkspaceAdministrationService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(minutes=1),
        id_factory=ids,
    )
    review = RiskReviewService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(minutes=2),
    )
    history = HistoryQueryService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(minutes=3),
    )
    notifications = NotificationService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(minutes=4),
    )
    security = WorkspaceSecurityService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(minutes=5),
        id_factory=ids,
    )
    cursor = CursorCodec(SECRET)
    oidc_config = GoogleOidcConfig(
        client_id="test-client-id",
        client_secret="provider-client-secret-must-not-leak",
        redirect_uri="http://testserver/api/v1/auth/google/callback",
        post_login_uri="http://testserver/app",
    )
    dependencies = ControlApiDependencies(
        auth=AuthRouterDependencies(oidc, oidc_config, authentication),
        workspaces=WorkspaceRouterDependencies(
            store,
            administration,
            authentication,
            cursor,
        ),
        risks=RiskRouterDependencies(store, review, history, authentication, cursor),
        history=HistoryRouterDependencies(history, authentication, cursor),
        security=SecurityRouterDependencies(security, authentication),
        notifications=NotificationRouterDependencies(
            notifications,
            authentication,
            cursor,
        ),
        session=ApplicationSessionConfig(
            secret_key=SECRET,
            https_only=False,
            max_age_seconds=3_600,
        ),
        hardening=hardening or ApplicationHardeningConfig(),
        observer=observer or StructuredLogger(),
    )
    app = FastAPI()
    create_control_api_bundle(dependencies).install(app)
    return app, store, oidc


def login(client: TestClient) -> tuple[str, str]:
    response = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert response.status_code in {302, 307}
    assert response.headers["location"].startswith(
        "https://accounts.example.invalid/authorize"
    )
    assert "httponly" in response.headers["set-cookie"].casefold()
    assert "samesite=lax" in response.headers["set-cookie"].casefold()

    callback = client.get("/api/v1/auth/google/callback", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "http://testserver/app"
    set_cookie = callback.headers["set-cookie"]
    assert "provider-client-secret" not in set_cookie
    assert "provider-access-token" not in set_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    return me.json()["id"], me.json()["csrf_token"]


def test_google_login_session_csrf_logout_and_safe_validation_errors() -> None:
    app, store, oidc = build_api()
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        user_id, csrf = login(client)
        assert oidc.callback_count == 1

        no_csrf = client.post("/api/v1/workspaces", json={"name": "Workspace"})
        assert no_csrf.status_code == 403

        invalid = client.post(
            "/api/v1/workspaces",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Workspace", "client_secret": "must-not-echo"},
        )
        assert invalid.status_code == 422
        assert "must-not-echo" not in invalid.text
        assert "client_secret" in invalid.text

        created = client.post(
            "/api/v1/workspaces",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Workspace"},
        )
        assert created.status_code == 201
        assert created.json()["owner_user_id"] == user_id

        logout = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )
        assert logout.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        relogged_user_id, _new_csrf = login(client)
        assert relogged_user_id == user_id
        assert oidc.callback_count == 2

    async def verify_revoked() -> None:
        async with store() as uow:
            user = await uow.users.get(user_id)
            assert user is not None and user.session_version == 1

    import asyncio

    asyncio.run(verify_revoked())


def test_control_workspace_risk_history_security_notification_routes() -> None:
    app, store, _oidc = build_api()
    with TestClient(app) as client:
        user_id, csrf = login(client)
        headers = {"X-CSRF-Token": csrf}
        created = client.post(
            "/api/v1/workspaces",
            headers=headers,
            json={"name": "Workspace", "description": "Control Plane"},
        )
        workspace = created.json()
        vws_id = workspace["id"]
        dashboard = client.get(f"/api/v1/workspaces/{vws_id}/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json() == {
            "new_risks": 0,
            "monitoring_risks": 0,
            "resolved_recently": 0,
            "analysis_failed": 0,
            "source_health": {
                "active": 0,
                "action_required": 0,
                "offline": 0,
                "disabled": 0,
            },
        }
        fetched_workspace = client.get(f"/api/v1/workspaces/{vws_id}")
        assert fetched_workspace.status_code == 200
        workspace_etag = fetched_workspace.headers["etag"]
        updated_workspace = client.patch(
            f"/api/v1/workspaces/{vws_id}",
            headers=headers,
            json={
                "expected_updated_at": workspace["updated_at"],
                "name": "Workspace Renamed",
            },
        )
        assert updated_workspace.status_code == 200
        assert updated_workspace.headers["etag"] != workspace_etag
        assert updated_workspace.json()["updated_at"] != workspace["updated_at"]

        second = client.post(
            "/api/v1/workspaces",
            headers=headers,
            json={"name": "Second"},
        )
        assert second.status_code == 201
        first_page = client.get("/api/v1/workspaces?limit=1")
        assert first_page.status_code == 200
        cursor = first_page.json()["next_cursor"]
        assert cursor
        assert client.get(
            "/api/v1/workspaces",
            params={"cursor": f"{cursor}tampered", "limit": 1},
        ).status_code == 400

        policy = client.put(
            f"/api/v1/workspaces/{vws_id}/security/ipriskignore",
            headers=headers,
            json={
                "expected_policy_version": "security-v1",
                "global_ignore_text": "/Backend/secrets/**\n",
            },
        )
        assert policy.status_code == 200
        assert policy.headers["etag"].startswith('"')
        assert policy.json()["changed"] is True
        assert policy.json()["settings"]["rule_count"] == 1
        policy_version = policy.json()["settings"]["policy_version"]
        stale = client.put(
            f"/api/v1/workspaces/{vws_id}/security/ipriskignore",
            headers=headers,
            json={
                "expected_policy_version": "security-v1",
                "global_ignore_text": "/Backend/other/**\n",
            },
        )
        assert stale.status_code == 409
        assert "Backend" not in stale.text

        async def seed_risk_and_notification() -> None:
            async with store() as uow:
                risk = Risk(
                    id="risk-1",
                    risk_workspace_id=vws_id,
                    artifact_id="artifact-1",
                    analysis_type=AnalysisType.PATENT,
                    risk_key="risk-key-1",
                    lifecycle_state=RiskLifecycleState.EXISTING,
                    review_disposition=ReviewDisposition.UNREVIEWED,
                    review_priority=ReviewPriority.HIGH,
                    summary="Potential overlap",
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                    latest_analysis_job_id="job-1",
                    updated_at=NOW,
                )
                await uow.risks.add(risk)
                await uow.risks.append_event(
                    RiskEvent(
                        id="risk-event-1",
                        risk_id=risk.id,
                        event_type=RiskEventType.DETECTED,
                        actor_type=ActorType.SYSTEM,
                        occurred_at=NOW,
                    )
                )
                await uow.notifications.add(
                    Notification(
                        id="notification-1",
                        user_id=user_id,
                        risk_workspace_id=vws_id,
                        notification_type=NotificationType.RISK_HIGH_DETECTED,
                        status=NotificationStatus.UNREAD,
                        created_at=NOW,
                        metadata_safe={
                            "risk_id": risk.id,
                            "access_token": "notification-secret",
                        },
                    )
                )
                await uow.audit.append_source_access(
                    SourceAccessEvent(
                        id="access-1",
                        risk_workspace_id=vws_id,
                        mount_id="mount-1",
                        artifact_id="artifact-1",
                        access_type=SourceAccessType.PARTIAL_CONTENT,
                        revision="/home/alice/private/source.py",
                        content_bytes=32,
                        occurred_at=NOW,
                        analysis_job_id="job-1",
                        provider_request_id="API_KEY=access-secret\nC:\\Users\\alice\\source.py",
                    )
                )
                await uow.commit()

        import asyncio

        asyncio.run(seed_risk_and_notification())

        detail = client.get(f"/api/v1/workspaces/{vws_id}/risks/risk-1")
        assert detail.status_code == 200
        assert detail.headers["etag"].startswith('"')
        assert detail.json()["open_original"] == {
            "action": "SOURCE_OPEN_ORIGINAL",
            "artifact_id": "artifact-1",
        }
        assert "source_content" not in detail.text

        reviewed = client.patch(
            f"/api/v1/workspaces/{vws_id}/risks/risk-1/review",
            headers=headers,
            json={
                "expected_review_version": 0,
                "disposition": "MONITORING",
                "comment": "reviewed",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.headers["etag"] != detail.headers["etag"]
        assert reviewed.json()["review_version"] == 1
        assert reviewed.json()["lifecycle_state"] == "EXISTING"

        timeline = client.get(
            f"/api/v1/workspaces/{vws_id}/risks/risk-1/timeline"
        )
        assert timeline.status_code == 200
        assert timeline.json()["entries"][0]["event_type"] == (
            "REVIEW_DISPOSITION_CHANGED"
        )

        activity = client.get(f"/api/v1/workspaces/{vws_id}/activity")
        assert activity.status_code == 200
        assert {item["stream"] for item in activity.json()["items"]} >= {
            "RISK",
            "AUDIT",
        }
        exported = client.get(f"/api/v1/workspaces/{vws_id}/audit/export")
        assert exported.status_code == 200
        assert "secrets/**" not in exported.text

        summary = client.get(
            f"/api/v1/workspaces/{vws_id}/security/data-access-summary"
        )
        assert summary.status_code == 200
        assert summary.json()["policy_version"] == policy_version
        assert summary.json()["raw_source_persisted"] is False
        assert "access-secret" not in summary.text
        assert "C:\\\\Users" not in summary.text
        assert "/home/alice" not in summary.text

        inbox = client.get("/api/v1/notifications")
        assert inbox.status_code == 200
        assert inbox.json()["unread_count"] == 1
        assert "notification-secret" not in inbox.text
        assert "[REDACTED_SECRET]" in inbox.text
        read = client.post(
            "/api/v1/notifications/notification-1/read",
            headers=headers,
        )
        assert read.status_code == 200
        assert read.json()["notification"]["status"] == "READ"


def test_unverified_google_email_is_rejected_without_session_or_raw_error() -> None:
    app, _store, _oidc = build_api(
        GoogleOidcIdentity(
            subject="unverified-subject",
            email="unverified@example.com",
            email_verified=False,
            display_name="Unverified",
        )
    )
    with TestClient(app) as client:
        client.get("/api/v1/auth/google/login", follow_redirects=False)
        callback = client.get(
            "/api/v1/auth/google/callback",
            follow_redirects=False,
        )
        assert callback.status_code == 401
        assert callback.json()["code"] == "AUTHENTICATION_REQUIRED"
        assert "unverified@example.com" not in callback.text
        assert client.get("/api/v1/auth/me").status_code == 401


def test_oidc_provider_start_failure_returns_safe_gateway_error() -> None:
    app, _store, oidc = build_api()

    async def fail(_request, _redirect_uri):
        raise RuntimeError("provider-client-secret-and-stack")

    oidc.authorize_redirect = fail
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/google/login",
            follow_redirects=False,
        )
        assert response.status_code == 502
        assert response.json()["code"] == "IDENTITY_PROVIDER_UNAVAILABLE"
        assert "provider-client-secret" not in response.text


def test_control_api_bundle_exposes_owned_routes_without_integration_wiring() -> None:
    app, _store, _oidc = build_api()
    paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/auth/google/login",
        "/api/v1/auth/google/callback",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/workspaces",
        "/api/v1/workspaces/{vws_id}",
        "/api/v1/workspaces/{vws_id}/dashboard",
        "/api/v1/invitations",
        "/api/v1/invitations/{invitation_id}/accept",
        "/api/v1/workspaces/{vws_id}/members",
        "/api/v1/workspaces/{vws_id}/members/invitations",
        "/api/v1/workspaces/{vws_id}/members/{user_id}",
        "/api/v1/workspaces/{vws_id}/mounts",
        "/api/v1/workspaces/{vws_id}/mounts/{mount_id}",
        "/api/v1/workspaces/{vws_id}/mounts/{mount_id}/alias",
        "/api/v1/workspaces/{vws_id}/mounts/{mount_id}/disable",
        "/api/v1/workspaces/{vws_id}/risks",
        "/api/v1/workspaces/{vws_id}/risks/{risk_id}",
        "/api/v1/workspaces/{vws_id}/risks/{risk_id}/review",
        "/api/v1/workspaces/{vws_id}/risks/{risk_id}/timeline",
        "/api/v1/workspaces/{vws_id}/activity",
        "/api/v1/workspaces/{vws_id}/audit",
        "/api/v1/workspaces/{vws_id}/source-access",
        "/api/v1/workspaces/{vws_id}/security",
        "/api/v1/workspaces/{vws_id}/security/ipriskignore",
        "/api/v1/workspaces/{vws_id}/security/data-access-summary",
        "/api/v1/notifications",
        "/api/v1/notifications/{notification_id}/read",
    }.issubset(paths)
    assert not any(path.startswith("/api/v1/source-connections") for path in paths)
    assert not any(path.startswith("/internal/") for path in paths)


def test_authenticated_user_explicitly_lists_and_accepts_email_invitation() -> None:
    app, store, _oidc = build_api()
    with TestClient(app) as client:
        user_id, csrf = login(client)
        invitation_id = invitation_id_for("invited-vws", "owner@example.com")

        async def seed() -> None:
            async with store() as uow:
                await uow.workspaces.add(
                    RiskWorkspace(
                        id="invited-vws",
                        name="Invited workspace",
                        owner_user_id="inviter-user",
                        security_policy_version="security-v1",
                        retention_policy_version="balanced-v1",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await uow.memberships.add_invitation(
                    MembershipInvitation(
                        id=invitation_id,
                        risk_workspace_id="invited-vws",
                        email="owner@example.com",
                        role=MembershipRole.RISK_REVIEWER,
                        status=InvitationStatus.PENDING,
                        invited_by="inviter-user",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await uow.commit()

        import asyncio

        asyncio.run(seed())
        pending = client.get("/api/v1/invitations")
        assert pending.status_code == 200
        assert pending.json()["items"][0]["workspace_name"] == "Invited workspace"
        assert pending.json()["items"][0]["acceptance_available"] is True

        no_csrf = client.post(f"/api/v1/invitations/{invitation_id}/accept")
        assert no_csrf.status_code == 403
        accepted = client.post(
            f"/api/v1/invitations/{invitation_id}/accept",
            headers={"X-CSRF-Token": csrf},
        )
        assert accepted.status_code == 200
        assert accepted.json()["membership"]["user_id"] == user_id
        assert accepted.json()["workspace"]["id"] == "invited-vws"
        assert client.get("/api/v1/invitations").json()["items"] == []
