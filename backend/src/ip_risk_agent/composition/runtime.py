"""Integration 이 주입하는 런타임 원시값.

`clock()` 은 timezone-aware UTC datetime 을, `id_factory(kind)` 는 외부 I/O 없이
비어 있지 않은 opaque ID 를 돌려줘야 한다 (AGENT_1_DELIVERY 4).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def utc_clock() -> datetime:
    return datetime.now(UTC)


def id_factory(kind: str) -> str:
    """추측 불가능한 ID. 종류를 접두사로 남겨 로그에서 식별할 수 있게 한다."""
    token = secrets.token_urlsafe(16)
    prefix = kind.strip().lower().replace(" ", "-") or "id"
    return f"{prefix}_{token}"


__all__ = ["id_factory", "utc_clock"]
