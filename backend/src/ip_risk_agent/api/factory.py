"""Integration-facing Control API router and secure session installation bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ip_risk_agent.application.observability import StructuredLogger

from .auth import AuthRouterDependencies, create_auth_router
from .common import install_error_handlers
from .history import HistoryRouterDependencies, create_history_router
from .notifications import (
    NotificationRouterDependencies,
    create_notifications_router,
)
from .risks import RiskRouterDependencies, create_risks_router
from .security import SecurityRouterDependencies, create_security_router
from .workspaces import (
    WorkspaceRouterDependencies,
    create_invitations_router,
    create_workspaces_router,
)
from .runtime import (
    ApiObservabilityMiddleware,
    ApplicationHardeningConfig,
    LocalRateLimitMiddleware,
)


@dataclass(frozen=True, slots=True)
class ApplicationSessionConfig:
    secret_key: str = field(repr=False)
    cookie_name: str = "iprisk_session"
    max_age_seconds: int = 8 * 60 * 60
    same_site: Literal["lax", "strict", "none"] = "lax"
    https_only: bool = True

    def __post_init__(self) -> None:
        if len(self.secret_key) < 32:
            raise ValueError("session secret_key must contain at least 32 characters")
        if not self.cookie_name or self.max_age_seconds < 60:
            raise ValueError("session cookie name and max age are invalid")
        if self.same_site == "none" and not self.https_only:
            raise ValueError("SameSite=None requires a secure cookie")


@dataclass(frozen=True, slots=True)
class ControlApiDependencies:
    auth: AuthRouterDependencies
    workspaces: WorkspaceRouterDependencies
    risks: RiskRouterDependencies
    history: HistoryRouterDependencies
    security: SecurityRouterDependencies
    notifications: NotificationRouterDependencies
    session: ApplicationSessionConfig
    hardening: ApplicationHardeningConfig = field(
        default_factory=ApplicationHardeningConfig
    )
    observer: StructuredLogger = field(default_factory=StructuredLogger)


class ControlApiBundle:
    def __init__(self, dependencies: ControlApiDependencies) -> None:
        self._dependencies = dependencies
        router = APIRouter()
        router.include_router(create_auth_router(dependencies.auth))
        router.include_router(create_workspaces_router(dependencies.workspaces))
        router.include_router(create_invitations_router(dependencies.workspaces))
        router.include_router(create_risks_router(dependencies.risks))
        router.include_router(create_history_router(dependencies.history))
        router.include_router(create_security_router(dependencies.security))
        router.include_router(create_notifications_router(dependencies.notifications))
        self.router = router

    def install(self, app: FastAPI) -> None:
        session = self._dependencies.session
        hardening = self._dependencies.hardening
        app.add_middleware(
            SessionMiddleware,
            secret_key=session.secret_key,
            session_cookie=session.cookie_name,
            max_age=session.max_age_seconds,
            same_site=session.same_site,
            https_only=session.https_only,
        )
        if hardening.allowed_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=list(hardening.allowed_origins),
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
            )
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=list(hardening.trusted_hosts),
        )
        if hardening.rate_limit_requests is not None:
            app.add_middleware(
                LocalRateLimitMiddleware,
                requests=hardening.rate_limit_requests,
                window_seconds=hardening.rate_limit_window_seconds,
                observer=self._dependencies.observer,
            )
        app.add_middleware(
            ApiObservabilityMiddleware,
            observer=self._dependencies.observer,
        )
        app.include_router(self.router)
        install_error_handlers(app, observer=self._dependencies.observer)


def create_control_api_bundle(dependencies: ControlApiDependencies) -> ControlApiBundle:
    return ControlApiBundle(dependencies)


__all__ = [
    "ApplicationSessionConfig",
    "ApplicationHardeningConfig",
    "ControlApiBundle",
    "ControlApiDependencies",
    "create_control_api_bundle",
]
