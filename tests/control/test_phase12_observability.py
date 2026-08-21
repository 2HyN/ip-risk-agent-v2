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


def test_intake_failure_reason_is_reported_as_a_safe_label():
    """클래스 이름만으로는 어떤 불변조건이 깨졌는지 알 수 없다.

    배포에서 `SourceChangeIntakeError` 만 보이고 사유가 없어 원인을 좁히지 못했다.
    메시지가 상수임을 스스로 보장하는 예외만 사유를 내놓는다.
    """
    import json

    from ip_risk_agent.application.observability import (
        ErrorCategory,
        SafeErrorDescriptor,
        StructuredLogger,
    )
    from ip_risk_agent.application.process_change.service import SourceChangeIntakeError

    written: list[dict] = []

    class Sink:
        def write(self, record: dict) -> None:
            written.append(record)

    logger = StructuredLogger(Sink())
    logger.error(
        SafeErrorDescriptor(
            category=ErrorCategory.INVALID_RESPONSE,
            public_code="safe_error",
            public_message="Safe error response",
            diagnostic_code="domain_validation_failed",
        ),
        exception=SourceChangeIntakeError(
            "analysis-bearing ChangeEvent must have exactly one AnalysisJob"
        ),
        status_code=422,
    )

    record = written[-1]
    assert record["provider_status_category"] == "SourceChangeIntakeError"
    assert record["diagnostic_reason"].startswith("analysis-bearing-ChangeEvent")
    # 레이블은 공백을 허용하지 않는다. 직렬화가 깨지면 안 된다.
    json.dumps(record)


def test_an_exception_without_safe_reason_reports_no_reason():
    """opt-in 이 아닌 예외는 종전과 같다. 임의 메시지를 흘리지 않는다."""
    from ip_risk_agent.application.observability import (
        ErrorCategory,
        SafeErrorDescriptor,
        StructuredLogger,
    )

    written: list[dict] = []

    class Sink:
        def write(self, record: dict) -> None:
            written.append(record)

    StructuredLogger(Sink()).error(
        SafeErrorDescriptor(
            category=ErrorCategory.INTERNAL,
            public_code="safe_error",
            public_message="Safe error response",
            diagnostic_code="unexpected_control_error",
        ),
        exception=ValueError("token=secret-value-should-not-appear"),
        status_code=500,
    )

    record = written[-1]
    assert "diagnostic_reason" not in record
    assert "secret-value-should-not-appear" not in str(record)
