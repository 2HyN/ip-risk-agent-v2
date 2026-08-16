"""Application user domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ip_risk_agent.core.common import (
    DomainInvariantError,
    normalize_utc,
    require_chronological,
    require_non_empty,
)


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class User:
    id: str
    google_subject: str
    email: str
    display_name: str
    created_at: datetime
    last_login_at: datetime
    avatar_url: str | None = None
    status: UserStatus = UserStatus.ACTIVE
    session_version: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_non_empty(self.id, "user.id"))
        object.__setattr__(
            self,
            "google_subject",
            require_non_empty(self.google_subject, "user.google_subject"),
        )
        object.__setattr__(self, "email", require_non_empty(self.email, "user.email"))
        object.__setattr__(
            self,
            "display_name",
            require_non_empty(self.display_name, "user.display_name"),
        )
        created_at = normalize_utc(self.created_at, "user.created_at")
        last_login_at = normalize_utc(self.last_login_at, "user.last_login_at")
        require_chronological(
            created_at,
            last_login_at,
            earlier_name="user.created_at",
            later_name="user.last_login_at",
        )
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "last_login_at", last_login_at)
        if (
            isinstance(self.session_version, bool)
            or not isinstance(self.session_version, int)
            or self.session_version < 0
        ):
            raise DomainInvariantError(
                "user.session_version must be a non-negative integer"
            )
