"""Small process-wide runtime primitives used by composition."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def opaque_id(kind: str) -> str:
    normalized = kind.strip().replace("_", "-")
    if not normalized:
        raise ValueError("opaque id kind must not be empty")
    return f"{normalized}-{secrets.token_urlsafe(24)}"


__all__ = ["opaque_id", "utc_now"]
