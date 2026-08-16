"""Shared Control API authentication, CSRF, pagination, and safe errors."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Annotated, Generic, TypeVar

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, ConfigDict

from ip_risk_agent.application.auth import (
    AuthenticatedSession,
    AuthenticationError,
    AuthenticationService,
)
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    RecordNotFoundError,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.risk_review import RiskReviewConflictError
from ip_risk_agent.application.security_policy import SecurityPolicyConflictError
from ip_risk_agent.application.workspace_admin import WorkspaceUpdateConflictError
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import DomainInvariantError
from ip_risk_agent.core.memberships import AuthorizationDeniedError

SESSION_KEY = "iprisk_app_auth"
CSRF_KEY = "iprisk_csrf"
T = TypeVar("T")


class StrictApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ApiError(StrictApiModel):
    code: str
    message: str
    details: list[dict[str, object]] | None = None


@dataclass(frozen=True, slots=True)
class CurrentPrincipal:
    user: User
    session: AuthenticatedSession


class CurrentPrincipalDependency:
    def __init__(self, authentication: AuthenticationService) -> None:
        self._authentication = authentication

    async def __call__(self, request: Request) -> CurrentPrincipal:
        value = request.session.get(SESSION_KEY)
        if not isinstance(value, dict):
            raise AuthenticationError("application session is missing")
        user_id = value.get("user_id")
        session_version = value.get("session_version")
        if (
            not isinstance(user_id, str)
            or isinstance(session_version, bool)
            or not isinstance(session_version, int)
        ):
            request.session.clear()
            raise AuthenticationError("application session is malformed")
        session = AuthenticatedSession(user_id, session_version)
        user = await self._authentication.resolve_session(session)
        return CurrentPrincipal(user, session)


class CsrfGuard:
    async def __call__(
        self,
        request: Request,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = request.session.get(CSRF_KEY)
        if (
            not isinstance(expected, str)
            or not isinstance(x_csrf_token, str)
            or not secrets.compare_digest(expected, x_csrf_token)
        ):
            raise CsrfValidationError("CSRF token validation failed")


class CsrfValidationError(PermissionError):
    pass


class OidcCallbackError(AuthenticationError):
    pass


class OidcProviderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CursorCodec:
    secret_key: str = field(repr=False)
    salt: str = "ip-risk-control-cursor-v1"

    def __post_init__(self) -> None:
        if len(self.secret_key) < 32:
            raise ValueError("cursor secret_key must contain at least 32 characters")

    def encode(self, *, scope: str, offset: int) -> str:
        return URLSafeSerializer(self.secret_key, salt=self.salt).dumps(
            {"scope": scope, "offset": offset}
        )

    def decode(self, value: str | None, *, scope: str) -> int:
        if value is None:
            return 0
        try:
            payload = URLSafeSerializer(self.secret_key, salt=self.salt).loads(value)
        except BadSignature as exc:
            raise InvalidCursorError("cursor signature is invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("scope") != scope
            or isinstance(payload.get("offset"), bool)
            or not isinstance(payload.get("offset"), int)
            or payload["offset"] < 0
        ):
            raise InvalidCursorError("cursor scope or offset is invalid")
        return payload["offset"]


class InvalidCursorError(ValueError):
    pass


class Page(StrictApiModel, Generic[T]):
    items: list[T]
    next_cursor: str | None


def paginate(
    values: tuple[T, ...],
    *,
    cursor: str | None,
    limit: int,
    scope: str,
    codec: CursorCodec,
) -> tuple[tuple[T, ...], str | None]:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    offset = codec.decode(cursor, scope=scope)
    selected = values[offset : offset + limit]
    next_offset = offset + len(selected)
    next_cursor = (
        codec.encode(scope=scope, offset=next_offset)
        if next_offset < len(values)
        else None
    )
    return selected, next_cursor


def opaque_etag(namespace: str, version: str) -> str:
    digest = sha256(f"{namespace}\x00{version}".encode("utf-8")).hexdigest()
    return f'"{digest}"'


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_error(_request: Request, _exc: AuthenticationError):
        return _error(401, "AUTHENTICATION_REQUIRED", "Authentication is required")

    @app.exception_handler(CsrfValidationError)
    async def csrf_error(_request: Request, _exc: CsrfValidationError):
        return _error(403, "CSRF_VALIDATION_FAILED", "CSRF validation failed")

    @app.exception_handler(OidcProviderUnavailableError)
    async def oidc_provider_error(_request: Request, _exc: OidcProviderUnavailableError):
        return _error(
            502,
            "IDENTITY_PROVIDER_UNAVAILABLE",
            "The identity provider is temporarily unavailable",
        )

    @app.exception_handler(AuthorizationDeniedError)
    async def authorization_error(_request: Request, _exc: AuthorizationDeniedError):
        return _error(403, "PERMISSION_DENIED", "Permission denied")

    @app.exception_handler(RecordNotFoundError)
    async def not_found_error(_request: Request, _exc: RecordNotFoundError):
        return _error(404, "NOT_FOUND", "The requested resource was not found")

    async def optimistic_conflict(_request: Request, _exc: Exception):
        return _error(409, "VERSION_CONFLICT", "The resource version is stale")

    app.add_exception_handler(RiskReviewConflictError, optimistic_conflict)
    app.add_exception_handler(SecurityPolicyConflictError, optimistic_conflict)
    app.add_exception_handler(WorkspaceUpdateConflictError, optimistic_conflict)
    app.add_exception_handler(ConcurrencyConflictError, optimistic_conflict)
    app.add_exception_handler(UniqueConstraintViolation, optimistic_conflict)

    @app.exception_handler(InvalidCursorError)
    async def cursor_error(_request: Request, _exc: InvalidCursorError):
        return _error(400, "INVALID_CURSOR", "The pagination cursor is invalid")

    @app.exception_handler(DomainInvariantError)
    async def domain_error(_request: Request, _exc: DomainInvariantError):
        return _error(422, "DOMAIN_VALIDATION_FAILED", "The request violates domain rules")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        details = [
            {"location": list(error["loc"]), "type": error["type"]}
            for error in exc.errors()
        ]
        return _error(
            422,
            "REQUEST_VALIDATION_FAILED",
            "The request is invalid",
            details,
        )


def _error(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiError(code=code, message=message, details=details).model_dump(
            mode="json", exclude_none=True
        ),
    )


__all__ = [
    "CSRF_KEY",
    "SESSION_KEY",
    "ApiError",
    "CsrfGuard",
    "CursorCodec",
    "CurrentPrincipal",
    "CurrentPrincipalDependency",
    "InvalidCursorError",
    "OidcCallbackError",
    "OidcProviderUnavailableError",
    "Page",
    "StrictApiModel",
    "install_error_handlers",
    "opaque_etag",
    "paginate",
]
