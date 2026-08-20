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

import httpx

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


async def with_http_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    provider: str,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """with_retry에 한 가지를 더한다 — httpx가 응답 자체를 못 받았을 때
    (DNS 실패, 연결 타임아웃, 연결 거부 등) 던지는 httpx.RequestError를
    TemporaryUnavailableError(retryable=True)로 먼저 바꿔준다.

    이게 없으면 "HTTP 상태코드가 5xx라서 실패"는 재시도되지만, "애초에
    응답을 못 받아서 실패"는 SourceConnectorError가 아니라서 with_retry가
    잡지도 못하고 그냥 새어나간다 — 실제로 이 문제를 재현해서 확인한 뒤
    추가했다."""

    async def _wrapped() -> T:
        try:
            return await fn()
        except httpx.RequestError as exc:
            raise TemporaryUnavailableError(
                provider=provider,
                safe_message=f"network error contacting {provider}: {type(exc).__name__}",
                retryable=True,
            ) from exc

    return await with_retry(
        _wrapped,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        sleep=sleep,
    )
