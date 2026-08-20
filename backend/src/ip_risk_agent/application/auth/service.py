"""Google identity upsert and server-revocable application sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
    UniqueConstraintViolation,
)
from ip_risk_agent.core.auth import User, UserStatus
from ip_risk_agent.core.common import DomainInvariantError, normalize_utc, stable_key

from .models import AuthenticatedSession, GoogleOidcIdentity

Clock = Callable[[], datetime]


class AuthenticationError(DomainInvariantError):
    pass


class AuthenticationService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
        concurrency_attempts: int = 3,
    ) -> None:
        if concurrency_attempts < 1:
            raise ValueError("concurrency_attempts must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._concurrency_attempts = concurrency_attempts

    async def authenticate_google_identity(
        self,
        identity: GoogleOidcIdentity,
    ) -> tuple[User, AuthenticatedSession]:
        if not identity.email_verified:
            raise AuthenticationError("Google account email is not verified")
        occurred_at = normalize_utc(self._clock(), "authentication.clock")
        last_conflict: ConcurrencyConflictError | UniqueConstraintViolation | None = None
        for _ in range(self._concurrency_attempts):
            try:
                user = await self._upsert_identity(identity, occurred_at)
                return user, AuthenticatedSession(user.id, user.session_version)
            except (ConcurrencyConflictError, UniqueConstraintViolation) as exc:
                last_conflict = exc
        assert last_conflict is not None
        raise last_conflict

    async def _upsert_identity(
        self,
        identity: GoogleOidcIdentity,
        occurred_at: datetime,
    ) -> User:
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get_by_google_subject(identity.subject)
            if user is None:
                user = User(
                    id=stable_key("google-user", (identity.subject,)),
                    google_subject=identity.subject,
                    email=identity.email,
                    display_name=identity.display_name,
                    avatar_url=identity.avatar_url,
                    created_at=occurred_at,
                    last_login_at=occurred_at,
                )
                await uow.users.add(user)
            else:
                if user.status is not UserStatus.ACTIVE:
                    raise AuthenticationError("application user is disabled")
                user = replace(
                    user,
                    email=identity.email,
                    display_name=identity.display_name,
                    avatar_url=identity.avatar_url,
                    last_login_at=max(user.last_login_at, occurred_at),
                )
                await uow.users.save(user)
            await uow.commit()
        return user

    async def resolve_session(self, session: AuthenticatedSession) -> User:
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(session.user_id)
        if (
            user is None
            or user.status is not UserStatus.ACTIVE
            or user.session_version != session.session_version
        ):
            raise AuthenticationError("application session is invalid or revoked")
        return user

    async def revoke_sessions(self, session: AuthenticatedSession) -> None:
        async with self._unit_of_work_factory() as uow:
            user = await uow.users.get(session.user_id)
            if user is None:
                raise RecordNotFoundError(f"user was not found: {session.user_id!r}")
            if user.session_version == session.session_version:
                await uow.users.save(
                    replace(user, session_version=user.session_version + 1)
                )
                await uow.commit()


__all__ = ["AuthenticationError", "AuthenticationService"]
