from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ip_risk_agent.api import ApplicationHardeningConfig
from ip_risk_agent.application.observability import (
    CorrelationIds,
    ErrorCategory,
    SafeErrorDescriptor,
    SafeLogValueError,
    StructuredLogger,
)
from test_control_api import build_api


class MemorySink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self.records.append(record)

    @property
    def serialized(self) -> str:
        return json.dumps(self.records, sort_keys=True)


def test_structured_logging_is_allow_listed_and_drops_unsafe_values() -> None:
    sink = MemorySink()
    observer = StructuredLogger(sink)
    correlation = CorrelationIds(
        request_id="request-1",
        event_id="event-1",
        analysis_job_id="job-1",
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        artifact_id="artifact-1",
    )
    observer.event(
        "analysis_completed",
        correlation=correlation,
        source_type="GITHUB",
        analyzer_type="PATENT",
        provider_status_category="AVAILABLE",
        latency_ms=42,
        candidate_count=3,
        coverage="COMPLETE",
        model_version="C:\\Users\\alice\\private\\source.py",
        prompt_version="Bearer provider-access-token-secret",
    )
    observer.error(
        SafeErrorDescriptor(
            ErrorCategory.PROVIDER_UNAVAILABLE,
            "PROVIDER_UNAVAILABLE",
            "The provider is temporarily unavailable",
            "provider_call_failed",
        ),
        exception=RuntimeError(
            "source text, full prompt, raw model response, Evidence, token=secret"
        ),
        correlation=correlation,
        status_code=502,
    )

    serialized = sink.serialized
    assert "request-1" in serialized
    assert "artifact-1" in serialized
    assert "model_version_omitted" in serialized
    assert "prompt_version_omitted" in serialized
    for forbidden in (
        "C:\\Users",
        "provider-access-token-secret",
        "source text",
        "full prompt",
        "raw model response",
        "Evidence",
        "token=secret",
    ):
        assert forbidden not in serialized
    assert sink.records[-1]["provider_status_category"] == "RuntimeError"


def test_correlation_ids_reject_paths_and_free_form_content() -> None:
    with pytest.raises(SafeLogValueError):
        CorrelationIds(artifact_id="/home/alice/private/source.py")
    with pytest.raises(TypeError):
        StructuredLogger().event(  # type: ignore[call-arg]
            "unsafe",
            source_content="raw source has no logging parameter",
        )


def test_api_request_id_safe_500_and_internal_diagnostic_separation() -> None:
    sink = MemorySink()
    app, _store, _oidc = build_api(observer=StructuredLogger(sink))

    @app.get("/api/v1/test/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("Bearer backend-secret and C:\\private\\source.py")

    with TestClient(app, raise_server_exceptions=False) as client:
        unauthorized = client.get(
            "/api/v1/auth/me",
            headers={"X-Request-ID": "caller-request-1"},
        )
        assert unauthorized.status_code == 401
        assert unauthorized.headers["x-request-id"] == "caller-request-1"

        unsafe_request_id = client.get(
            "/api/v1/auth/me",
            headers={"X-Request-ID": "/tmp/private/source.py"},
        )
        assert unsafe_request_id.headers["x-request-id"] != "/tmp/private/source.py"

        failed = client.get("/api/v1/test/unexpected")
        assert failed.status_code == 500
        assert failed.json() == {
            "code": "INTERNAL_ERROR",
            "message": "The request could not be completed",
        }
        assert "backend-secret" not in failed.text
        assert "private" not in failed.text

    assert "backend-secret" not in sink.serialized
    assert "C:\\\\private" not in sink.serialized
    assert any(
        record.get("diagnostic_code") == "unexpected_control_error"
        and record.get("error_category") == "INTERNAL"
        for record in sink.records
    )


def test_explicit_host_cors_and_local_rate_limit_hardening() -> None:
    hardening = ApplicationHardeningConfig(
        trusted_hosts=("testserver",),
        allowed_origins=("https://app.example.test",),
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )
    app, _store, _oidc = build_api(hardening=hardening)
    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": "https://app.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == (
            "https://app.example.test"
        )
        assert client.get("/api/v1/auth/me").status_code == 401
        limited = client.get("/api/v1/auth/me")
        assert limited.status_code == 429
        assert limited.json()["code"] == "RATE_LIMITED"
        assert limited.headers["retry-after"] == "60"
        assert "x-request-id" in limited.headers

    host_only_app, _store, _oidc = build_api(
        hardening=ApplicationHardeningConfig(trusted_hosts=("testserver",))
    )
    with TestClient(host_only_app, base_url="http://untrusted.example") as client:
        assert client.get("/api/v1/auth/me").status_code == 400


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allowed_origins": ("*",)},
        {"allowed_origins": ("https://app.example.test/path",)},
        {"trusted_hosts": ()},
        {"rate_limit_requests": 0},
    ],
)
def test_hardening_config_fails_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ApplicationHardeningConfig(**kwargs)  # type: ignore[arg-type]
