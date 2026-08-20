"""HTTP status code -> SourceConnectorError 매핑 (Drive와 동일 패턴)."""

from __future__ import annotations

from ..common.errors import (
    AuthRequiredError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    SourceConnectorError,
    TemporaryUnavailableError,
)

_RETRYABLE_SERVER_STATUSES = {500, 502, 503, 504}


def map_github_status_code(status_code: int, safe_message: str) -> SourceConnectorError:
    if status_code == 401:
        return AuthRequiredError(provider="github", safe_message=safe_message)
    if status_code == 403:
        return PermissionDeniedError(provider="github", safe_message=safe_message)
    if status_code == 404:
        return NotFoundError(provider="github", safe_message=safe_message)
    if status_code == 429:
        return RateLimitedError(provider="github", safe_message=safe_message)
    if status_code in _RETRYABLE_SERVER_STATUSES:
        return TemporaryUnavailableError(provider="github", safe_message=safe_message)
    return TemporaryUnavailableError(provider="github", safe_message=safe_message, retryable=False)
