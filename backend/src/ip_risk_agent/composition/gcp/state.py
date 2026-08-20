"""Firestore 기반 ``OAuthStateStore``.

in-memory 구현은 프로세스 안에서만 유효하다. Cloud Run 은 인스턴스를 여러 개
띄우므로, OAuth 시작을 처리한 인스턴스와 콜백을 받는 인스턴스가 다를 수 있다.
그러면 state 를 찾지 못해 정상 로그인이 CSRF 거부로 실패한다. 다중 인스턴스
환경에서는 이 구현이 **필수**다.

state 는 일회용이다. ``consume`` 은 읽는 즉시 삭제해 재사용을 막는다.
만료된 state 는 읽지 않고 버린다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

COLLECTION = "integration_oauth_states"
DEFAULT_TTL_SECONDS = 10 * 60


class FirestoreOAuthStateStore:
    """``OAuthStateStore`` Protocol 의 운영 구현.

    Control 의 canonical collection 을 건드리지 않는다. Integration 소유
    collection 하나만 쓴다.
    """

    def __init__(
        self,
        *,
        project_id: str,
        database: str = "(default)",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        client: object | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id is required for the OAuth state store")
        if ttl_seconds < 60:
            raise ValueError("oauth state ttl must be at least 60 seconds")
        self._project_id = project_id
        self._database = database
        self._ttl = timedelta(seconds=ttl_seconds)
        self._client = client

    def _collection(self):
        if self._client is None:
            from google.cloud import firestore  # noqa: PLC0415 - 지연 import

            self._client = firestore.Client(
                project=self._project_id, database=self._database
            )
        return self._client.collection(COLLECTION)

    async def save(self, state: str, context: dict) -> None:
        if not state:
            raise ValueError("oauth state must not be empty")
        now = datetime.now(UTC)

        def _call() -> None:
            self._collection().document(state).set(
                {
                    "context": dict(context),
                    "created_at": now,
                    "expires_at": now + self._ttl,
                }
            )

        await asyncio.to_thread(_call)

    async def consume(self, state: str) -> dict | None:
        if not state:
            return None

        def _call() -> dict | None:
            reference = self._collection().document(state)
            snapshot = reference.get()
            if not snapshot.exists:
                return None
            # 일회용이다. 유효하든 만료됐든 읽는 즉시 지운다.
            reference.delete()
            payload = snapshot.to_dict() or {}
            expires_at = payload.get("expires_at")
            if expires_at is not None and expires_at < datetime.now(UTC):
                return None
            context = payload.get("context")
            return dict(context) if isinstance(context, dict) else None

        return await asyncio.to_thread(_call)


__all__ = ["COLLECTION", "DEFAULT_TTL_SECONDS", "FirestoreOAuthStateStore"]
