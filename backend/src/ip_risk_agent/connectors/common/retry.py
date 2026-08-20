"""외부 API 호출 재시도 (지수 백오프 + jitter). Master Spec Phase F "retries" 항목.

TemporaryUnavailableError(retryable=True)와 RateLimitedError만 재시도한다 —
AuthRequiredError, PermissionDeniedError, NotFoundError 같은 건 다시 불러도
똑같은 결과가 나올 뿐이라 재시도 대상이 아니다 (Phase A의 8종 에러 분류를
그대로 활용).
"""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar

from .errors import RateLimitedError, SourceConnectorError, TemporaryUnavailableError

T = TypeVar("T")


def is_retryable(error: SourceConnectorError) -> bool:
    if isinstance(error, RateLimitedError):
        return True
    if isinstance(error, TemporaryUnavailableError):
        return error.retryable
    return False


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """fn()을 실행하고, 재시도 가능한 에러면 지수 백오프(+jitter)로 최대
    max_attempts번까지 다시 시도한다. 재시도 불가능한 에러거나 마지막
    시도까지 실패하면 원래 에러를 그대로 던진다 (실패를 성공으로 숨기지
    않는다 — Master Spec §59 금지사항 9번)."""

    attempt = 0
    while True:
        attempt += 1
        try:
            return await fn()
        except SourceConnectorError as exc:
            if attempt >= max_attempts or not is_retryable(exc):
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            jitter = random.uniform(0, delay * 0.25)
            await sleep(delay + jitter)
