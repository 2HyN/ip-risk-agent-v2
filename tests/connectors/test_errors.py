"""errors.py의 8개 카테고리가 정확히 매핑되는지 확인한다."""

from __future__ import annotations

import pytest

from ip_risk_agent.connectors.common.errors import (
    AuthRequiredError,
    InvalidWebhookError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    SourceConnectorError,
    SourceErrorCategory,
    SourceOfflineError,
    TemporaryUnavailableError,
    UnsupportedContentError,
    to_provider_failure_fields,
)
from iprisk_contracts.common import ProviderFailure


@pytest.mark.parametrize(
    ("error_cls", "category", "default_retryable"),
    [
        (AuthRequiredError, SourceErrorCategory.AUTH_REQUIRED, False),
        (PermissionDeniedError, SourceErrorCategory.PERMISSION_DENIED, False),
        (NotFoundError, SourceErrorCategory.NOT_FOUND, False),
        (RateLimitedError, SourceErrorCategory.RATE_LIMITED, True),
        (TemporaryUnavailableError, SourceErrorCategory.TEMPORARY_UNAVAILABLE, True),
        (UnsupportedContentError, SourceErrorCategory.UNSUPPORTED_CONTENT, False),
        (InvalidWebhookError, SourceErrorCategory.INVALID_WEBHOOK, False),
        (SourceOfflineError, SourceErrorCategory.SOURCE_OFFLINE, True),
    ],
)
def test_each_category_maps_correctly(error_cls, category, default_retryable):
    err = error_cls(provider="github", safe_message="something safe to show")

    assert err.category is category
    assert err.retryable is default_retryable
    assert err.provider == "github"
    assert err.safe_message == "something safe to show"


def test_retryable_override():
    err = RateLimitedError(provider="drive", safe_message="slow down", retryable=False)
    assert err.retryable is False


def test_is_subclass_of_base():
    err = NotFoundError(provider="local", safe_message="missing")
    assert isinstance(err, SourceConnectorError)


def test_to_provider_failure_fields_matches_contract():
    err = TemporaryUnavailableError(provider="kipris-like-example", safe_message="timeout")

    fields = to_provider_failure_fields(err)

    # 실제 shared contract 모델에 그대로 넣어도 검증을 통과해야 한다.
    failure = ProviderFailure(**fields)

    assert failure.provider == "kipris-like-example"
    assert failure.category == "TEMPORARY_UNAVAILABLE"
    assert failure.retryable is True
    assert failure.safe_message == "timeout"
