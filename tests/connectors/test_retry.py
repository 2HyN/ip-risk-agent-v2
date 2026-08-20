from __future__ import annotations

import asyncio

import pytest

from ip_risk_agent.connectors.common.errors import (
    NotFoundError,
    RateLimitedError,
    TemporaryUnavailableError,
)
from ip_risk_agent.connectors.common.retry import is_retryable, with_retry


async def _no_sleep(seconds: float) -> None:
    pass


def test_is_retryable_rate_limited_true():
    assert is_retryable(RateLimitedError(provider="github", safe_message="x")) is True


def test_is_retryable_temporary_unavailable_respects_flag():
    assert is_retryable(TemporaryUnavailableError(provider="github", safe_message="x", retryable=True)) is True
    assert is_retryable(TemporaryUnavailableError(provider="github", safe_message="x", retryable=False)) is False


def test_is_retryable_not_found_false():
    assert is_retryable(NotFoundError(provider="github", safe_message="x")) is False


def test_succeeds_on_first_try_without_retrying():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            return "ok"

        result = await with_retry(fn, sleep=_no_sleep)
        assert result == "ok"
        assert calls == 1

    asyncio.run(scenario())


def test_retries_then_succeeds():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TemporaryUnavailableError(provider="github", safe_message="flaky", retryable=True)
            return "ok"

        result = await with_retry(fn, max_attempts=5, sleep=_no_sleep)
        assert result == "ok"
        assert calls == 3

    asyncio.run(scenario())


def test_gives_up_after_max_attempts():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise TemporaryUnavailableError(provider="github", safe_message="always flaky", retryable=True)

        with pytest.raises(TemporaryUnavailableError):
            await with_retry(fn, max_attempts=3, sleep=_no_sleep)
        assert calls == 3

    asyncio.run(scenario())


def test_non_retryable_error_fails_immediately():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise NotFoundError(provider="github", safe_message="gone")

        with pytest.raises(NotFoundError):
            await with_retry(fn, max_attempts=5, sleep=_no_sleep)
        assert calls == 1

    asyncio.run(scenario())


def test_rate_limited_is_retried():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise RateLimitedError(provider="github", safe_message="slow down")
            return "ok"

        result = await with_retry(fn, sleep=_no_sleep)
        assert result == "ok"
        assert calls == 2

    asyncio.run(scenario())


def test_delay_grows_exponentially_with_jitter():
    async def scenario():
        recorded_delays: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            recorded_delays.append(seconds)

        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            if calls < 4:
                raise TemporaryUnavailableError(provider="github", safe_message="x", retryable=True)
            return "ok"

        await with_retry(fn, max_attempts=5, base_delay_seconds=1.0, sleep=fake_sleep)

        assert len(recorded_delays) == 3
        assert 1.0 <= recorded_delays[0] < 1.25
        assert 2.0 <= recorded_delays[1] < 2.5
        assert 4.0 <= recorded_delays[2] < 5.0

    asyncio.run(scenario())
