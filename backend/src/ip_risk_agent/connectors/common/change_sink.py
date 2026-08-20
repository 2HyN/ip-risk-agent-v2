"""SourceChange -> Control Plane 전달 포트.

Master Spec §40(Cloud Tasks Boundary): 실제 persist + idempotency +
enqueue는 Control Plane의 책임이다. Agent 2는 만들어진 SourceChange를
"넘겨주는" 지점까지만 소유한다. Integration이 이 Protocol을 Control의
실제 persist/enqueue 로직에 연결한다.
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.source_change import SourceChange


class SourceChangeSink(Protocol):
    async def persist(self, change: SourceChange) -> None: ...


class InMemorySourceChangeSink:
    """개발/테스트 전용 fake. 받은 change를 리스트에 쌓기만 한다."""

    def __init__(self) -> None:
        self.received: list[SourceChange] = []

    async def persist(self, change: SourceChange) -> None:
        self.received.append(change)
