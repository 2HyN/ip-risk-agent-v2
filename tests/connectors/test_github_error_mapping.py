from __future__ import annotations

import pytest

from ip_risk_agent.connectors.common.errors import (
    AuthRequiredError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    TemporaryUnavailableError,
)
from ip_risk_agent.connectors.github.error_mapping import map_github_status_code


@pytest.mark.parametrize(
    ("status_code", "expected_cls"),
    [
        (401, AuthRequiredError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (429, RateLimitedError),
        (500, TemporaryUnavailableError),
        (503, TemporaryUnavailableError),
    ],
)
def test_known_status_codes_map_correctly(status_code, expected_cls):
    error = map_github_status_code(status_code, "safe message")
    assert isinstance(error, expected_cls)


def test_unknown_status_code_falls_back_to_non_retryable_temporary():
    error = map_github_status_code(418, "teapot")
    assert isinstance(error, TemporaryUnavailableError)
    assert error.retryable is False
