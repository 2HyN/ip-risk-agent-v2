"""Google App Login HTTP routes."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse

from ip_risk_agent.application.auth import AuthenticationService

from ..common import (
    CSRF_KEY,
    SESSION_KEY,
    CsrfGuard,
    CurrentPrincipal,
    CurrentPrincipalDependency,
    OidcCallbackError,
    OidcProviderUnavailableError,
    StrictApiModel,
)
from .oidc import GoogleOidcClient, GoogleOidcConfig


class UserResponse(StrictApiModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    csrf_token: str


@dataclass(frozen=True, slots=True)
class AuthRouterDependencies:
    oidc: GoogleOidcClient
    oidc_config: GoogleOidcConfig
    authentication: AuthenticationService


def create_auth_router(dependencies: AuthRouterDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
    current = CurrentPrincipalDependency(dependencies.authentication)
    csrf = CsrfGuard()

    @router.get("/google/login", response_class=RedirectResponse)
    async def google_login(request: Request):
        request.session.clear()
        try:
            return await dependencies.oidc.authorize_redirect(
                request,
                dependencies.oidc_config.redirect_uri,
            )
        except Exception:
            request.session.clear()
            raise OidcProviderUnavailableError(
                "Google OIDC authorization could not be started"
            ) from None

    @router.get("/google/callback", response_class=RedirectResponse)
    async def google_callback(request: Request):
        try:
            identity = await dependencies.oidc.fetch_identity(request)
            _user, session = await dependencies.authentication.authenticate_google_identity(
                identity
            )
        except Exception as exc:
            request.session.clear()
            raise OidcCallbackError("Google OIDC callback failed") from None
        request.session.clear()
        request.session[SESSION_KEY] = {
            "user_id": session.user_id,
            "session_version": session.session_version,
        }
        request.session[CSRF_KEY] = secrets.token_urlsafe(32)
        return RedirectResponse(
            dependencies.oidc_config.post_login_uri,
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ) -> Response:
        await dependencies.authentication.revoke_sessions(principal.session)
        request.session.clear()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/me", response_model=UserResponse)
    async def me(
        request: Request,
        principal: CurrentPrincipal = Depends(current),
    ) -> UserResponse:
        csrf_token = request.session.get(CSRF_KEY)
        if not isinstance(csrf_token, str):
            csrf_token = secrets.token_urlsafe(32)
            request.session[CSRF_KEY] = csrf_token
        return UserResponse(
            id=principal.user.id,
            email=principal.user.email,
            display_name=principal.user.display_name,
            avatar_url=principal.user.avatar_url,
            csrf_token=csrf_token,
        )

    return router


__all__ = ["AuthRouterDependencies", "UserResponse", "create_auth_router"]
