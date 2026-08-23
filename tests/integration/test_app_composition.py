from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.responses import RedirectResponse

from ip_risk_agent.application.auth import GoogleOidcIdentity
from ip_risk_agent.composition.app import create_api_app
from ip_risk_agent.composition.container import ContainerOverrides, build_container
from ip_risk_agent.composition.providers import SourceRouterBundle
from ip_risk_agent.composition.settings import AppRole, RuntimeProfile, Settings

SESSION_SECRET = "phase-4-api-session-secret-at-least-32-characters"


class FakeOidc:
    async def authorize_redirect(self, request, redirect_uri):
        request.session["oidc"] = "bound"
        return RedirectResponse("https://accounts.example.invalid/authorize")

    async def fetch_identity(self, request):
        assert request.session.pop("oidc") == "bound"
        return GoogleOidcIdentity(
            subject="owner-subject",
            email="owner@example.com",
            email_verified=True,
            display_name="Owner",
        )


def api_settings() -> Settings:
    return Settings(
        profile=RuntimeProfile.TEST,
        role=AppRole.API,
        log_level="INFO",
        public_base_url="http://testserver",
        session_secret=SESSION_SECRET,
    )


def test_api_hosts_built_product_routes_same_origin(tmp_path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<main>product</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    settings = replace(api_settings(), frontend_dist_dir=str(tmp_path))
    app = create_api_app(build_container(settings))

    client = TestClient(app)
    product = client.get("/app")
    assert product.text == "<main>product</main>"
    assert product.headers["cache-control"] == "no-cache"
    assert client.get("/w/workspace-1/sources").text == "<main>product</main>"
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "console.log('ok')"


def test_integrated_api_mounts_control_source_health_and_runs_lifespan_cleanup() -> None:
    source = APIRouter()

    @source.get("/api/v1/source-composition-probe")
    async def probe():
        return {"status": "mounted"}

    closed: list[bool] = []

    async def close() -> None:
        closed.append(True)

    container = build_container(
        api_settings(),
        overrides=ContainerOverrides(
            oidc_client=FakeOidc(),
            source_routers=SourceRouterBundle(web=(source,)),
            close_callbacks=(close,),
        ),
    )
    app = create_api_app(container)
    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/source-composition-probe" in paths
    assert "/health/live" in paths and "/health/ready" in paths
    assert "/api/v1/runtime-config" in paths
    assert "/api/v1/desktop/enrollment-challenges" in paths
    assert "/api/v1/desktop/devices/{device_id}/revoke" in paths
    assert any("open-original" in path for path in paths)

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok", "checks": {}}
        readiness = client.get("/health/ready")
        assert readiness.status_code == 200
        assert readiness.json()["checks"] == {
            "canonical_store": "in_memory",
            "task_queue": "in_memory",
        }
        assert client.get("/api/v1/source-composition-probe").json() == {
            "status": "mounted"
        }
        assert client.get("/api/v1/runtime-config").json() == {
            # D1 — 화면이 알아야 할 것은 어디로 공유하는가 하나뿐이다. Picker 는
            # 브라우저 API 키를 내려보내야 했는데, 공유 주소는 알아도 접근이
            # 생기지 않는다.
            "drive_sharing": {
                "enabled": False,
                "sharing_address": None,
            }
        }
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get(
            "/api/v1/auth/google/login", follow_redirects=False
        ).status_code in {302, 307}
        assert client.get(
            "/api/v1/auth/google/callback", follow_redirects=False
        ).status_code == 303
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        enrollment = client.post(
            "/api/v1/desktop/enrollment-challenges",
            headers={"X-CSRF-Token": me.json()["csrf_token"]},
        )
        assert enrollment.status_code == 200
        assert enrollment.json()["expires_in_seconds"] == 300
        created = client.post(
            "/api/v1/workspaces",
            headers={"X-CSRF-Token": me.json()["csrf_token"]},
            json={"name": "Integrated workspace"},
        )
        assert created.status_code == 201
    assert closed == [True]
