"""제한된 재시도.

Cloud Tasks 가 바깥에서 이미 재시도한다. 여기서 길게 끌면 두 겹이 곱해져
지연과 비용만 늘어난다. 짧고 적게 한다 (Agent 3 Spec 41).

재시도 후에도 실패한 것을 빈 성공으로 바꾸지 않는다. 그것이 이 모듈의 유일한 금기다.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from ..common.errors import ProviderFailureError

T = TypeVar("T")


@dataclass(frozen=True)
class RetryBudget:
    """시도 횟수와 대기 시간."""

    attempts: int = 2
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 4.0
    jitter: float = 0.25

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """지수 백오프. 여러 작업이 동시에 재시도해 몰리지 않도록 흔들어 준다."""
        raw = min(self.base_delay_seconds * (2**attempt), self.max_delay_seconds)
        spread = raw * self.jitter
        source = rng or random
        return raw + source.uniform(-spread, spread)


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    budget: RetryBudget,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> T:
    """재시도 가능한 실패에만 다시 시도한다.

    인증 실패나 검증 실패는 다시 해도 결과가 같으므로 즉시 올린다.
    """
    last: ProviderFailureError | None = None
    for attempt in range(budget.attempts):
        try:
            return await operation()
        except ProviderFailureError as failure:
            if not failure.retryable:
                raise
            last = failure
            if attempt + 1 < budget.attempts:
                await sleep(budget.delay_for(attempt, rng))
    assert last is not None  # attempts >= 1 이면 반드시 채워진다
    raise last
