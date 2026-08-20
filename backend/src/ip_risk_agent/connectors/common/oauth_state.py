"""OAuth/설치 흐름의 CSRF state 저장. Drive/GitHub 공용.

Agent2 Spec §7: "CSRF/state validation 필수", "OAuth callback은 pending
connection context를 복구해야 한다".
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Protocol


def generate_state() -> str:
    return secrets.token_urlsafe(32)


class OAuthStateStore(Protocol):
    async def save(self, state: str, context: dict) -> None: ...
    async def consume(self, state: str) -> dict | None: ...


class InMemoryOAuthStateStore:
    """개발/테스트 전용. 프로덕션은 여러 인스턴스가 떠 있을 수 있어서
    state를 발급한 인스턴스와 콜백을 받는 인스턴스가 다를 수 있다 —
    Firestore 등 공유 저장소로 교체해야 한다."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl_seconds = ttl_seconds
        self._data: dict[str, tuple[dict, datetime]] = {}

    async def save(self, state: str, context: dict) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds)
        self._data[state] = (context, expires_at)

    async def consume(self, state: str) -> dict | None:
        entry = self._data.pop(state, None)
        if entry is None:
            return None
        context, expires_at = entry
        if datetime.now(timezone.utc) > expires_at:
            return None
        return context
