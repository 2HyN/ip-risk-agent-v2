"""ChangeEvent relay — Cloud Tasks 경계를 넘기 위한 Integration 소유 저장소.

--------------------------------------------------------------------------
왜 필요한가
--------------------------------------------------------------------------
큐는 content-free ID 하나만 넘긴다.

    TaskEnqueuer.enqueue_change(change_event_id: str)

그런데 워커가 다음에 해야 하는 일은 ``SourceChange`` 전체를 요구한다.

    SourceAdapter.fetch_snapshot(change: SourceChange)

``ControlPlaneFacade`` 의 공개 메서드 중 ``change_event_id`` 로 ``SourceChange``
를 되짚는 것이 없다. 그래서 ID 만 받은 워커는 아무것도 할 수 없다.

--------------------------------------------------------------------------
어떻게 푸는가
--------------------------------------------------------------------------
Source 라우터가 넘긴 ``SourceChange`` 를 Control 에 등록하는 길목(sink)에서
Integration 이 자기 소유 collection 에 함께 적어 둔다. 워커는 ID 로 그것을
읽어 파이프라인을 잇는다.

이 방식이 경계를 지키는 이유:

- **Control 내부를 조회하지 않는다.** canonical collection 을 읽지 않고
  Integration 이 스스로 받은 값을 자기 collection 에 보관할 뿐이다.
- **원본이 새지 않는다.** ``SourceChange`` 는 Frozen Contract 상 content-free
  다 (Master Spec 10). 파일 내용·자격증명·로컬 절대경로가 애초에 담기지 않는다.
- **정본이 아니다.** 판단의 근거는 여전히 Control 의 ChangeEvent 다. 여기 있는
  것은 워커에게 전달하기 위한 사본이며, 없으면 실패로 남고 성공으로 위장하지
  않는다.

더 깔끔한 해법은 Control 이 조회 메서드를 하나 공개하는 것이다. 그때는 이
모듈을 지우고 그 메서드를 쓰면 된다. contract-change request 로 올려 두었다
(``contract-change-requests/``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol

from iprisk_contracts import SourceChange

COLLECTION = "integration_change_relay"
# 큐 재시도와 dead-letter 처리 여유를 포함한다. 그 뒤에는 남겨 둘 이유가 없다.
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60


class ChangeRelayStore(Protocol):
    """change_event_id 로 ``SourceChange`` 를 되찾는 포트."""

    async def remember(self, change_event_id: str, change: SourceChange) -> None: ...

    async def resolve(self, change_event_id: str) -> SourceChange | None: ...


class InMemoryChangeRelayStore:
    """단일 프로세스용. 개발과 테스트에서 쓴다."""

    def __init__(self) -> None:
        self._store: dict[str, SourceChange] = {}

    async def remember(self, change_event_id: str, change: SourceChange) -> None:
        self._store[change_event_id] = change

    async def resolve(self, change_event_id: str) -> SourceChange | None:
        return self._store.get(change_event_id)


class FirestoreChangeRelayStore:
    """Cloud Run 다중 인스턴스에서 쓰는 운영 구현."""

    def __init__(
        self,
        *,
        project_id: str,
        database: str = "(default)",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        client: object | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id is required for the change relay store")
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

    async def remember(self, change_event_id: str, change: SourceChange) -> None:
        if not change_event_id:
            raise ValueError("change_event_id must not be empty")
        now = datetime.now(UTC)
        # Contract 를 그대로 직렬화한다. 손으로 필드를 고르면 Contract 가 바뀔 때
        # 조용히 어긋난다.
        payload = change.model_dump(mode="json")

        def _call() -> None:
            self._collection().document(change_event_id).set(
                {
                    "change": payload,
                    "created_at": now,
                    "expires_at": now + self._ttl,
                }
            )

        await asyncio.to_thread(_call)

    async def resolve(self, change_event_id: str) -> SourceChange | None:
        if not change_event_id:
            return None

        def _call() -> dict | None:
            snapshot = self._collection().document(change_event_id).get()
            if not snapshot.exists:
                return None
            document = snapshot.to_dict() or {}
            expires_at = document.get("expires_at")
            if expires_at is not None and expires_at < datetime.now(UTC):
                return None
            change = document.get("change")
            return change if isinstance(change, dict) else None

        payload = await asyncio.to_thread(_call)
        if payload is None:
            return None
        return SourceChange.model_validate(payload)


__all__ = [
    "COLLECTION",
    "DEFAULT_TTL_SECONDS",
    "ChangeRelayStore",
    "FirestoreChangeRelayStore",
    "InMemoryChangeRelayStore",
]
