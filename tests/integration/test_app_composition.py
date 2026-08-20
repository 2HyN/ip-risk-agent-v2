"""조립된 애플리케이션이 실제로 서는지 검증한다.

Master Spec 55 의 Integration 테스트 범위 — 한 Plane 안에서는 확인할 수 없는
경계만 다룬다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ip_risk_agent.composition import create_app

from .conftest import build_test_container, login


def route_paths(app) -> set[str]:
    """등록된 모든 경로를 모은다.

    FastAPI 는 `include_router` 결과를 `_IncludedRouter` 로 감싸 담기 때문에
    `app.routes` 를 한 겹만 훑으면 하위 라우트가 보이지 않는다. 그래서
    중첩된 router 를 따라 내려간다.
    """
    found: set[str] = set()

    def walk(routes) -> None:
        for route in routes:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                found.add(path)
            nested = getattr(route, "routes", None)
            if nested:
                walk(nested)
            # FastAPI 의 `_IncludedRouter` 는 원본 라우터를 이 이름으로 들고 있다.
            for attr in ("router", "original_router"):
                inner = getattr(route, attr, None)
                if inner is not None and getattr(inner, "routes", None):
                    walk(inner.routes)

    walk(app.routes)
    return found


def test_health_reports_what_is_actually_wired(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    # 자격증명이 없는 환경이므로 in-memory 로 내려가야 한다.
    assert payload["control_backend"] == "in-memory"
    assert payload["google_login"] == "unconfigured"
    assert payload["intelligence"] == "disabled"
    # Local 은 외부 자격증명이 필요 없으므로 항상 붙는다.
    assert payload["sources"]["mounted"] == ["local"]
    # 붙지 않은 provider 는 이유가 드러나야 한다.
    assert set(payload["sources"]["skipped"]) == {"google_drive", "github"}


def test_health_never_leaks_secrets(client: TestClient) -> None:
    body = client.get("/health").text
    assert "integration-test-session-secret" not in body
    assert "SESSION_SECRET" not in body


def test_control_and_source_routes_are_mounted_on_one_app(client: TestClient) -> None:
    paths = route_paths(client.app)
    # Agent 1 소유
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/workspaces" in paths
    # Agent 2 소유
    assert "/desktop/mounts/register" in paths
    assert "/desktop/events" in paths


def test_provider_routers_appear_once_configured() -> None:
    """자격증명이 생기면 연결 시작 라우터가 붙는다.

    Drive/GitHub 는 단계별로 조립된다. OAuth·설치 시작은 조회 포트가 없어도
    되지만, Mount 생성과 webhook 은 provider 식별자 매핑(Firestore)이 있어야
    한다. 없으면 **붙이지 않고 이유를 남긴다** — 반쯤 조립해 런타임에 실패하게
    두지 않는다.
    """
    container = build_test_container(
        {
            "GOOGLE_DRIVE_CLIENT_ID": "drive-client",
            "GOOGLE_DRIVE_CLIENT_SECRET": "drive-secret",
            "GOOGLE_DRIVE_REDIRECT_URI": "http://testserver/oauth/drive",
            "GITHUB_APP_ID": "12345",
            "GITHUB_APP_SLUG": "ip-risk-agent",
        }
    )
    with TestClient(create_app(container=container)) as client:
        sources = client.get("/health").json()["sources"]
        assert "google_drive:oauth" in sources["mounted"]
        assert "github:install" in sources["mounted"]

        paths = route_paths(client.app)
        assert "/api/v1/source-connections/google-drive/start" in paths
        assert "/api/v1/source-connections/github/install/start" in paths

        # Firestore 가 없으므로 Drive 의 뒷단계는 붙지 않아야 한다.
        assert "google_drive:bindings" in sources["skipped"]
        # GitHub 은 private key 까지 있어야 adapter 를 만들 수 있고,
        # 그 사실이 "Firestore 미설정"과 구분되어 드러나야 한다.
        assert "github:private_key" in sources["skipped"]


def test_incomplete_provider_config_does_not_mount_half_a_router() -> None:
    """설정이 부분적일 때 무엇이 왜 빠졌는지 `/health` 가 밝힌다."""
    container = build_test_container(
        {
            "GOOGLE_DRIVE_CLIENT_ID": "drive-client",
            "GOOGLE_DRIVE_CLIENT_SECRET": "drive-secret",
            "GOOGLE_DRIVE_REDIRECT_URI": "http://testserver/oauth/drive",
        }
    )
    with TestClient(create_app(container=container)) as client:
        sources = client.get("/health").json()["sources"]
        paths = route_paths(client.app)

        # 연결 시작은 열리고
        assert "/api/v1/source-connections/google-drive/start" in paths
        # Mount 생성·webhook 은 열리지 않는다
        assert "/webhooks/google-drive" not in paths
        assert "google_drive:mounts" not in sources["mounted"]
        assert "google_drive:webhook" not in sources["mounted"]
        # 이유가 남는다
        assert sources["skipped"]["google_drive:bindings"]


def test_login_roundtrip_establishes_a_session(client: TestClient) -> None:
    user_id, csrf_token = login(client)
    assert user_id
    assert csrf_token

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == user_id


def test_google_login_fails_closed_when_unconfigured() -> None:
    """가짜 클라이언트를 주입하지 않으면 로그인 경로가 열려서는 안 된다."""
    from ip_risk_agent.composition import build_container

    container = build_container(
        {
            "SESSION_SECRET": "integration-test-session-secret-value-0001",
            "APP_PUBLIC_BASE_URL": "http://testserver",
        }
    )
    with TestClient(create_app(container=container)) as client:
        response = client.get("/api/v1/auth/google/login", follow_redirects=False)
        # 안전한 게이트웨이 오류. 인증 우회 경로는 존재하지 않는다.
        assert response.status_code == 502
        assert "unconfigured" not in response.text.casefold()


@pytest.mark.parametrize(
    "path",
    ["/api/v1/auth/me", "/api/v1/workspaces", "/api/v1/notifications"],
)
def test_control_routes_require_a_session(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
