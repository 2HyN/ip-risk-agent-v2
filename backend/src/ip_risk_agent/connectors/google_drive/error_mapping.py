"""HTTP status code -> SourceConnectorError 매핑 (googleapiclient 비의존).

client.py가 실제 HttpError에서 status code만 뽑아 여기 넘기는 방식으로 써서,
googleapiclient 설치 여부와 무관하게 매핑 로직 자체는 지금 바로 테스트할 수 있다.
"""

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


def map_drive_status_code(status_code: int, safe_message: str) -> SourceConnectorError:
    if status_code == 401:
        return AuthRequiredError(provider="google_drive", safe_message=safe_message)
    if status_code == 403:
        return PermissionDeniedError(provider="google_drive", safe_message=safe_message)
    if status_code == 404:
        return NotFoundError(provider="google_drive", safe_message=safe_message)
    if status_code == 429:
        return RateLimitedError(provider="google_drive", safe_message=safe_message)
    if status_code in _RETRYABLE_SERVER_STATUSES:
        return TemporaryUnavailableError(provider="google_drive", safe_message=safe_message)
    return TemporaryUnavailableError(
        provider="google_drive", safe_message=safe_message, retryable=False
    )
