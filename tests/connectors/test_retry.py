from __future__ import annotations

import asyncio

import httpx

import pytest

from ip_risk_agent.connectors.common.errors import (
    NotFoundError,
    RateLimitedError,
    TemporaryUnavailableError,
)
from ip_risk_agent.connectors.common.retry import is_retryable, with_http_retry, with_retry


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



def test_with_http_retry_translates_network_error_and_retries():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise httpx.ConnectError("connection refused")
            return "ok"

        result = await with_http_retry(fn, provider="github", sleep=_no_sleep)
        assert result == "ok"
        assert calls == 2

    asyncio.run(scenario())


def test_with_http_retry_gives_up_after_max_attempts_on_persistent_network_error():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise httpx.ConnectTimeout("timed out")

        with pytest.raises(TemporaryUnavailableError):
            await with_http_retry(fn, provider="github", max_attempts=3, sleep=_no_sleep)
        assert calls == 3

    asyncio.run(scenario())


def test_with_http_retry_still_respects_non_retryable_source_errors():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise NotFoundError(provider="github", safe_message="gone")

        with pytest.raises(NotFoundError):
            await with_http_retry(fn, provider="github", max_attempts=5, sleep=_no_sleep)
        assert calls == 1

    asyncio.run(scenario())


def test_with_http_retry_reproduces_the_real_unreachable_host_bug_fixed():
    """이전엔 with_retry만 썼을 때 이 시나리오가 재시도 없이 바로 터졌다
    (실제로 재현해서 확인함). with_http_retry로는 재시도 후 최종 실패해도
    최소한 SourceConnectorError로 변환은 된다."""

    async def scenario():
        async def call_unreachable():
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.get("https://this-domain-does-not-exist-12345.invalid/")
            return resp

        with pytest.raises(TemporaryUnavailableError):
            await with_http_retry(call_unreachable, provider="github", max_attempts=2, sleep=_no_sleep)

    asyncio.run(scenario())


def test_with_http_retry_translates_network_error_and_retries():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise httpx.ConnectError("connection refused")
            return "ok"

        result = await with_http_retry(fn, provider="github", sleep=_no_sleep)
        assert result == "ok"
        assert calls == 2

    asyncio.run(scenario())


def test_with_http_retry_gives_up_after_max_attempts_on_persistent_network_error():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise httpx.ConnectTimeout("timed out")

        with pytest.raises(TemporaryUnavailableError):
            await with_http_retry(fn, provider="github", max_attempts=3, sleep=_no_sleep)
        assert calls == 3

    asyncio.run(scenario())


def test_with_http_retry_still_respects_non_retryable_source_errors():
    async def scenario():
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise NotFoundError(provider="github", safe_message="gone")

        with pytest.raises(NotFoundError):
            await with_http_retry(fn, provider="github", max_attempts=5, sleep=_no_sleep)
        assert calls == 1

    asyncio.run(scenario())


def test_with_http_retry_reproduces_the_real_unreachable_host_bug_fixed():
    """이전엔 with_retry만 썼을 때 이 시나리오가 재시도 없이 바로 터졌다
    (실제로 재현해서 확인함). with_http_retry로는 재시도 후 최종 실패해도
    최소한 SourceConnectorError로 변환은 된다."""

    async def scenario():
        async def call_unreachable():
            async with httpx.AsyncClient(timeout=1.0) as client:
                resp = await client.get("https://this-domain-does-not-exist-12345.invalid/")
            return resp

        with pytest.raises(TemporaryUnavailableError):
            await with_http_retry(call_unreachable, provider="github", max_attempts=2, sleep=_no_sleep)

    asyncio.run(scenario())