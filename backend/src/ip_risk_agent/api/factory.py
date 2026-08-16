"""Integration-facing Control API router and secure session installation bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, FastAPI
from starlette.middleware.sessions import SessionMiddleware

from .auth import AuthRouterDependencies, create_auth_router
from .common import install_error_handlers
from .history import HistoryRouterDependencies, create_history_router
from .notifications import (
    NotificationRouterDependencies,
    create_notifications_router,
)
from .risks import RiskRouterDependencies, create_risks_router
from .security import SecurityRouterDependencies, create_security_router
from .workspaces import WorkspaceRouterDependencies, create_workspaces_router


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


class ControlApiBundle:
    def __init__(self, dependencies: ControlApiDependencies) -> None:
        self._dependencies = dependencies
        router = APIRouter()
        router.include_router(create_auth_router(dependencies.auth))
        router.include_router(create_workspaces_router(dependencies.workspaces))
        router.include_router(create_risks_router(dependencies.risks))
        router.include_router(create_history_router(dependencies.history))
        router.include_router(create_security_router(dependencies.security))
        router.include_router(create_notifications_router(dependencies.notifications))
        self.router = router

    def install(self, app: FastAPI) -> None:
        session = self._dependencies.session
        app.add_middleware(
            SessionMiddleware,
            secret_key=session.secret_key,
            session_cookie=session.cookie_name,
            max_age=session.max_age_seconds,
            same_site=session.same_site,
            https_only=session.https_only,
        )
        app.include_router(self.router)
        install_error_handlers(app)


def create_control_api_bundle(dependencies: ControlApiDependencies) -> ControlApiBundle:
    return ControlApiBundle(dependencies)


__all__ = [
    "ApplicationSessionConfig",
    "ControlApiBundle",
    "ControlApiDependencies",
    "create_control_api_bundle",
]
