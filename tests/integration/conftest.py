"""통합 테스트 공용 설비.

외부 자원을 요구하지 않는다. Control 저장소는 in-memory, Google OIDC 는
가짜 클라이언트를 주입한다 — Agent 1 이 자신의 API 테스트에서 쓰는 방식과 같다
(tests/control/test_control_api.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ip_risk_agent.application.auth import GoogleOidcIdentity
from ip_risk_agent.composition import build_container, create_app

DEFAULT_ENV = {
    # 32자 이상이어야 세션 설정이 통과한다. 실제 비밀값이 아니다.
    "SESSION_SECRET": "integration-test-session-secret-value-0001",
    "APP_PUBLIC_BASE_URL": "http://testserver",
}


class FakeGoogleOidcClient:
    """상태/논스 왕복만 흉내 낸다. 네트워크를 쓰지 않는다."""

    def __init__(self, identity: GoogleOidcIdentity) -> None:
        self.identity = identity
        self.callback_count = 0

    async def authorize_redirect(self, request: Request, redirect_uri: str):
        request.session["fake_oidc_state"] = "state-bound-to-signed-session"
        request.session["fake_oidc_nonce"] = "nonce-bound-to-signed-session"
        return RedirectResponse("https://accounts.example.invalid/authorize?state=opaque")

    async def fetch_identity(self, request: Request) -> GoogleOidcIdentity:
        assert request.session.pop("fake_oidc_state") == "state-bound-to-signed-session"
        assert request.session.pop("fake_oidc_nonce") == "nonce-bound-to-signed-session"
        self.callback_count += 1
        return self.identity


def build_test_container(env: dict[str, str] | None = None, **overrides):
    identity = overrides.pop(
        "identity",
        GoogleOidcIdentity(
            subject="google-subject-1",
            email="owner@example.com",
            email_verified=True,
            display_name="Owner",
        ),
    )
    merged = {**DEFAULT_ENV, **(env or {})}
    return build_container(
        merged, oidc_client=FakeGoogleOidcClient(identity), **overrides
    )


@pytest.fixture
def container():
    return build_test_container()


@pytest.fixture
def client(container):
    with TestClient(create_app(container=container)) as test_client:
        yield test_client


def login(client: TestClient) -> tuple[str, str]:
    """로그인 왕복을 마치고 (user_id, csrf_token) 을 돌려준다."""
    start = client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert start.status_code in {302, 307}
    callback = client.get("/api/v1/auth/google/callback", follow_redirects=False)
    assert callback.status_code == 303
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    payload = me.json()
    return payload["id"], payload["csrf_token"]
