"""Google Drive OAuth 흐름. Agent2 Spec §7-9.

drive.file 최소권한 + CSRF state 검증 + refresh token을 credential_vault에
저장하는 것까지가 우리 책임. SourceConnection의 canonical 생성/저장은
Control 몫이라 콜백으로 넘긴다 (connection_creation_callback).
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

import httpx

from ..common.errors import AuthRequiredError

GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_OAUTH_SCOPES = "openid email https://www.googleapis.com/auth/drive.file"


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


class DriveOAuthClient(Protocol):
    async def exchange_code(self, code: str) -> dict: ...


class HttpxDriveOAuthClient:
    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    async def exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
        if resp.status_code >= 400:
            raise AuthRequiredError(
                provider="google_drive", safe_message="failed to exchange authorization code"
            )
        return resp.json()


def decode_identity_from_id_token(id_token: str) -> tuple[str, str]:
    """id_token(JWT)에서 provider_subject(sub)/provider_email을 꺼낸다.

    여기서는 서명 검증을 하지 않는다 — 이 값은 "어느 계정을 연결했는지"
    표시용일 뿐, 실제 보안 결정(진짜 인증)은 state CSRF 검증과 code
    exchange 자체(HTTPS + client_secret 소유)에서 이미 끝난 상태다.
    프로덕션에서 더 엄격하게 가려면 Google JWKS로 서명 검증을 추가할 수
    있다 — known limitation으로 문서화함."""

    if not id_token:
        return "", ""

    import jwt as pyjwt

    claims = pyjwt.decode(id_token, options={"verify_signature": False})
    return claims.get("sub", ""), claims.get("email", "")
