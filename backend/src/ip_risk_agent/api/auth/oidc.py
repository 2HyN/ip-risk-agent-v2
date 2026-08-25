"""Authlib-backed Google OIDC web client; tokens never leave this adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import Response

from ip_risk_agent.application.auth import GoogleOidcIdentity

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


class GoogleOidcClient(Protocol):
    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response: ...
    async def fetch_identity(self, request: Request) -> GoogleOidcIdentity: ...


@dataclass(frozen=True, slots=True)
class GoogleOidcConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    post_login_uri: str
    discovery_url: str = GOOGLE_DISCOVERY_URL

    def __post_init__(self) -> None:
        for field_name in (
            "client_id",
            "client_secret",
            "redirect_uri",
            "post_login_uri",
            "discovery_url",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"google_oidc.{field_name} must not be empty")
        for field_name in ("redirect_uri", "post_login_uri"):
            parsed = urlsplit(getattr(self, field_name))
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
            ):
                raise ValueError(f"google_oidc.{field_name} must be an HTTP(S) URL")
        discovery = urlsplit(self.discovery_url)
        if discovery.scheme != "https" or not discovery.netloc:
            raise ValueError("google_oidc.discovery_url must be an HTTPS URL")


class AuthlibGoogleOidcClient:
    def __init__(self, config: GoogleOidcConfig) -> None:
        self._oauth = OAuth()
        self._client = self._oauth.register(
            name="google",
            client_id=config.client_id,
            client_secret=config.client_secret,
            server_metadata_url=config.discovery_url,
            client_kwargs={
                "scope": "openid email profile",
                "code_challenge_method": "S256",
            },
        )

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        # prompt=select_account — 구글 세션이 살아 있어도 계정 선택 화면을 강제한다.
        # 없으면 로그아웃해도 "구글로 계속" 이 직전 계정으로 조용히 재로그인되어,
        # 공용 기기·복수 계정(팀 시연) 환경에서 다른 계정으로 들어갈 길이 없다.
        return await self._client.authorize_redirect(
            request, redirect_uri, prompt="select_account"
        )

    async def fetch_identity(self, request: Request) -> GoogleOidcIdentity:
        token = await self._client.authorize_access_token(request)
        claims = token.get("userinfo")
        if not hasattr(claims, "get"):
            raise ValueError("verified OIDC userinfo is missing")
        return GoogleOidcIdentity(
            subject=claims.get("sub", ""),
            email=claims.get("email", ""),
            email_verified=claims.get("email_verified", False),
            display_name=claims.get("name") or claims.get("email", ""),
            avatar_url=claims.get("picture"),
        )


__all__ = [
    "AuthlibGoogleOidcClient",
    "GOOGLE_DISCOVERY_URL",
    "GoogleOidcClient",
    "GoogleOidcConfig",
]
