"""초당 호출 제한.

KIPRIS 유료 전환으로 월 한도는 사라졌지만 초당 호출 제한은 남았다
(`docs/PATENT_RAG_ENHANCEMENT_PLAN.md` §0). 검색을 넓히면(질의 12 × rows 30)
동시 호출이 늘어나므로 클라이언트가 스스로 속도를 조인다.

기존 세마포어(`kipris.py`)는 **동시성**만 조이고 초당 횟수는 조이지 않는다.
둘은 다른 제약이라 함께 쓴다 — 세마포어가 겹침을, 버킷이 속도를 맡는다.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """초당 ``rate_per_sec`` 개의 토큰이 차오르는 버킷.

    ``acquire`` 는 토큰이 생길 때까지 기다린다. 잠금 밖에서 잔다 — 기다리는 동안
    다른 코루틴의 토큰 계산을 막지 않는다.

    시계는 주입 가능하다. 시험이 실제로 잠들지 않고 대기 시간을 검증하기 위해서다.
    """

    def __init__(
        self,
        rate_per_sec: float,
        capacity: float | None = None,
        *,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self._rate = rate_per_sec
        self._capacity = capacity if capacity is not None else max(1.0, rate_per_sec)
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = self._clock()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._last) * self._rate
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await self._sleep(wait)


__all__ = ["TokenBucket"]
