"""Web UI 를 API 와 같은 origin 에서 서빙할 때의 경계 검증.

가장 위험한 실패는 SPA fallback 이 API 경로를 삼키는 것이다. 그러면 API 호출이
404 대신 HTML 을 받고, 프론트엔드에서는 "JSON 파싱 실패"로만 보여 원인을 찾기
어렵다. 그 상태가 다시 생기지 않게 잠근다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ip_risk_agent.composition import create_app
from ip_risk_agent.composition.static import is_reserved

from .conftest import build_test_container


@pytest.fixture
def dist(tmp_path, monkeypatch):
    """빌드 산출물 흉내. 실제 번들 없이 라우팅만 본다."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=root></div>", "utf-8")
    (root / "assets" / "index-abc.js").write_text("console.log(1)", "utf-8")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(root))
    return root


@pytest.fixture
def web_client(dist):
    with TestClient(create_app(container=build_test_container())) as client:
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "api/v1/auth/me",
        "api/v1/workspaces",
        "webhooks/github",
        "desktop/events",
        "internal/analysis/run",
        "health",
        "docs",
        "openapi.json",
    ],
)
def test_api_owned_paths_are_never_treated_as_spa_routes(path: str) -> None:
    assert is_reserved(path), f"{path} 가 SPA fallback 으로 넘어간다"


@pytest.mark.parametrize(
    "path",
    ["", "login", "w/vws-1/risks", "w/vws-1/risks/risk-1/timeline", "notifications"],
)
def test_client_routes_are_not_reserved(path: str) -> None:
    assert not is_reserved(path), f"{path} 는 SPA 가 처리해야 한다"


def test_root_serves_the_app_instead_of_404(web_client: TestClient) -> None:
    """번들이 없을 때 루트가 404 를 내던 문제를 잠근다."""
    response = web_client.get("/")
    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_client_side_route_survives_a_refresh(web_client: TestClient) -> None:
    """새로고침해도 index.html 을 받아야 클라이언트 라우팅이 이어진다."""
    response = web_client.get("/w/vws-1/risks")
    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_assets_are_served_as_files(web_client: TestClient) -> None:
    response = web_client.get("/assets/index-abc.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_still_answers_with_json_not_html(web_client: TestClient) -> None:
    """SPA 를 붙인 뒤에도 API 가 그대로 동작해야 한다."""
    unauthorized = web_client.get("/api/v1/auth/me")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["content-type"].startswith("application/json")

    health = web_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_unknown_api_path_returns_404_not_the_app(web_client: TestClient) -> None:
    """없는 API 경로에 HTML 을 돌려주면 호출부가 원인을 알 수 없게 된다."""
    response = web_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert "<div id=root>" not in response.text


def test_health_reports_whether_the_web_bundle_is_present(
    web_client: TestClient,
) -> None:
    assert web_client.get("/health").json()["web"] == "served"


def test_without_a_bundle_the_api_keeps_working(monkeypatch) -> None:
    """번들이 없는 배포도 유효하다. API 만 뜨고 루트는 404 다."""
    monkeypatch.delenv("FRONTEND_DIST_DIR", raising=False)
    with TestClient(create_app(container=build_test_container())) as client:
        assert client.get("/health").json()["web"] == "not-bundled"
        assert client.get("/").status_code == 404
        assert client.get("/api/v1/auth/me").status_code == 401


def test_path_traversal_cannot_escape_the_bundle(web_client: TestClient) -> None:
    """`..` 로 이미지 안의 다른 파일을 읽을 수 없어야 한다."""
    response = web_client.get("/../../etc/passwd")
    # 정규화되어 index.html 로 떨어지거나 거부된다. 파일 내용이 새면 안 된다.
    assert response.status_code in {200, 400, 404}
    assert "root:" not in response.text


def test_index_is_never_cached(web_client: TestClient) -> None:
    """index.html 경로는 고정인데 참조하는 자산 해시는 배포마다 바뀐다.

    브라우저가 옛 index.html 을 재사용하면 이미 사라진 해시 파일을 찾아
    흰 화면이 되거나, 옛 코드가 돌아 "배포가 반영되지 않은" 것처럼 보인다.
    """
    for path in ("/", "/w/vws-1/risks"):
        cache_control = web_client.get(path).headers.get("cache-control", "")
        assert "no-store" in cache_control, f"{path} 가 캐시될 수 있다"


def test_hashed_assets_stay_cacheable(web_client: TestClient) -> None:
    """자산은 파일명에 해시가 있어 캐시해도 안전하다. 같이 막으면 손해다."""
    assert "no-store" not in web_client.get(
        "/assets/index-abc.js"
    ).headers.get("cache-control", "")
