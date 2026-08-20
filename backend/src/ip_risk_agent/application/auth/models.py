"""Verified Google OIDC identity and application-session values."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ip_risk_agent.core.common import DomainInvariantError, require_non_empty


@dataclass(frozen=True, slots=True)
class GoogleOidcIdentity:
    subject: str
    email: str
    email_verified: bool
    display_name: str
    avatar_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", require_non_empty(self.subject, "oidc.subject"))
        normalized_email = require_non_empty(self.email, "oidc.email").casefold()
        local, separator, domain = normalized_email.rpartition("@")
        if not separator or not local or not domain:
            raise DomainInvariantError("oidc.email must be a valid email address")
        object.__setattr__(self, "email", normalized_email)
        object.__setattr__(
            self,
            "display_name",
            require_non_empty(self.display_name, "oidc.display_name")[:200],
        )
        if not isinstance(self.email_verified, bool):
            raise DomainInvariantError("oidc.email_verified must be boolean")
        if self.avatar_url is not None:
            parsed = urlsplit(self.avatar_url.strip())
            if parsed.scheme != "https" or not parsed.netloc or parsed.username is not None:
                raise DomainInvariantError("oidc.avatar_url must be an HTTPS URL")
            object.__setattr__(
                self,
                "avatar_url",
                urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:2_048],
            )


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user_id: str
    session_version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", require_non_empty(self.user_id, "session.user_id"))
        if (
            isinstance(self.session_version, bool)
            or not isinstance(self.session_version, int)
            or self.session_version < 0
        ):
            raise DomainInvariantError("session.session_version must be non-negative")


__all__ = ["AuthenticatedSession", "GoogleOidcIdentity"]
