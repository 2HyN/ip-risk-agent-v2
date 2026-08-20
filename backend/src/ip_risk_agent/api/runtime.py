"""ASGI observability, host/origin policy, and bounded local rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.responses import JSONResponse

from ip_risk_agent.application.observability import (
    CorrelationIds,
    ErrorCategory,
    StructuredLogger,
    bind_correlation,
    reset_correlation,
)

AsgiApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ApplicationHardeningConfig:
    """Deployment inputs without assuming the Integration proxy topology."""

    trusted_hosts: tuple[str, ...] = ("testserver", "localhost", "127.0.0.1")
    allowed_origins: tuple[str, ...] = ()
    rate_limit_requests: int | None = None
    rate_limit_window_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.trusted_hosts or any(
            not host or "/" in host or "://" in host for host in self.trusted_hosts
        ):
            raise ValueError("trusted_hosts must contain host patterns only")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("allowed_origins must contain explicit HTTP(S) origins")
        if self.rate_limit_requests is not None and self.rate_limit_requests < 1:
            raise ValueError("rate_limit_requests must be positive when enabled")
        if self.rate_limit_window_seconds < 1:
            raise ValueError("rate_limit_window_seconds must be positive")


class ApiObservabilityMiddleware:
    def __init__(self, app: AsgiApp, *, observer: StructuredLogger) -> None:
        self._app = app
        self._observer = observer

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = _incoming_request_id(scope) or uuid4().hex
        correlation = CorrelationIds(request_id=request_id)
        token = bind_correlation(correlation)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", ()))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        self._observer.event("http_request_started", correlation=correlation)
        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            latency_ms = max(0, round((time.perf_counter() - started) * 1000))
            self._observer.event(
                "http_request_completed",
                correlation=correlation,
                latency_ms=latency_ms,
                status_code=status_code,
            )
            reset_correlation(token)


class LocalRateLimitMiddleware:
    """Single-process safety net; ingress remains authoritative in production."""

    def __init__(
        self,
        app: AsgiApp,
        *,
        requests: int,
        window_seconds: int,
        observer: StructuredLogger,
    ) -> None:
        self._app = app
        self._requests = requests
        self._window = window_seconds
        self._observer = observer
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        client_key = client[0] if client else "unknown"
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets[client_key]
            while bucket and bucket[0] <= now - self._window:
                bucket.popleft()
            allowed = len(bucket) < self._requests
            if allowed:
                bucket.append(now)
            elif not bucket:
                self._buckets.pop(client_key, None)
        if allowed:
            await self._app(scope, receive, send)
            return
        self._observer.event(
            "http_rate_limited",
            error_category=ErrorCategory.RATE_LIMIT,
            diagnostic_code="api_rate_limit_exceeded",
            status_code=429,
        )
        response = JSONResponse(
            status_code=429,
            content={
                "code": "RATE_LIMITED",
                "message": "Too many requests",
            },
            headers={"Retry-After": str(self._window)},
        )
        await response(scope, receive, send)


def _incoming_request_id(scope: dict[str, Any]) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == b"x-request-id":
            try:
                candidate = value.decode("ascii")
                return CorrelationIds(request_id=candidate).request_id
            except (UnicodeDecodeError, ValueError):
                return None
    return None


__all__ = [
    "ApiObservabilityMiddleware",
    "ApplicationHardeningConfig",
    "LocalRateLimitMiddleware",
]
