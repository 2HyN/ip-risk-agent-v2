"""Allow-listed structured observability for the Control Plane.

The logger intentionally has no free-form metadata argument.  Callers can only
provide the identifiers and operational summaries approved by the master spec;
raw source, credentials, prompts, model responses, evidence, and local paths
therefore have no logging surface.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")


class SafeLogValueError(ValueError):
    """Raised before a value that is unsafe for structured logs is emitted."""


class ErrorCategory(StrEnum):
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNSUPPORTED = "UNSUPPORTED"
    INTERNAL = "INTERNAL"


def _safe_label(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_LABEL.fullmatch(value) is None:
        raise SafeLogValueError(f"{field_name} must be an opaque safe label")
    return value


@dataclass(frozen=True, slots=True)
class CorrelationIds:
    request_id: str | None = None
    event_id: str | None = None
    analysis_job_id: str | None = None
    risk_workspace_id: str | None = None
    mount_id: str | None = None
    artifact_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            _safe_label(value, field_name)

    def merged(self, **values: str | None) -> CorrelationIds:
        current = asdict(self)
        current.update({key: value for key, value in values.items() if value is not None})
        return CorrelationIds(**current)


@dataclass(frozen=True, slots=True)
class SafeErrorDescriptor:
    """Public error semantics kept separate from internal diagnostics."""

    category: ErrorCategory
    public_code: str
    public_message: str
    diagnostic_code: str

    def __post_init__(self) -> None:
        _safe_label(self.public_code, "public_code")
        _safe_label(self.diagnostic_code, "diagnostic_code")
        if not self.public_message or len(self.public_message) > 200:
            raise ValueError("public_message must be between 1 and 200 characters")


class StructuredEventSink(Protocol):
    def write(self, record: dict[str, object]) -> None: ...


class PythonLoggingSink:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("ip_risk_agent.control")

    def write(self, record: dict[str, object]) -> None:
        self._logger.info(
            json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        )


class StructuredLogger:
    """Emit schema-stable JSON records through an allow-listed interface."""

    def __init__(self, sink: StructuredEventSink | None = None) -> None:
        self._sink = sink or PythonLoggingSink()

    def event(
        self,
        event_name: str,
        *,
        correlation: CorrelationIds | None = None,
        source_type: str | None = None,
        analyzer_type: str | None = None,
        provider_status_category: str | None = None,
        latency_ms: int | None = None,
        candidate_count: int | None = None,
        coverage: str | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        error_category: ErrorCategory | None = None,
        diagnostic_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        record: dict[str, object] = {
            "schema_version": 1,
            "event": _safe_label(event_name, "event_name"),
        }
        identifiers = asdict(correlation or current_correlation())
        record.update({key: value for key, value in identifiers.items() if value is not None})
        labels = {
            "source_type": source_type,
            "analyzer_type": analyzer_type,
            "provider_status_category": provider_status_category,
            "coverage": coverage,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "diagnostic_code": diagnostic_code,
        }
        for field_name, value in labels.items():
            try:
                safe = _safe_label(value, field_name)
            except SafeLogValueError:
                # Version/provider labels can originate outside Control.  An
                # unsafe label is omitted without failing an already-committed
                # business operation or copying the rejected value.
                record[f"{field_name}_omitted"] = True
                continue
            if safe is not None:
                record[field_name] = safe
        for field_name, value in {
            "latency_ms": latency_ms,
            "candidate_count": candidate_count,
            "status_code": status_code,
        }.items():
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise SafeLogValueError(f"{field_name} must be a non-negative integer")
                record[field_name] = value
        if error_category is not None:
            record["error_category"] = error_category.value
        self._sink.write(record)

    def error(
        self,
        descriptor: SafeErrorDescriptor,
        *,
        exception: BaseException | None = None,
        correlation: CorrelationIds | None = None,
        status_code: int | None = None,
    ) -> None:
        # Only the exception class name is diagnostic.  str(exception), args,
        # traceback locals, and provider payloads are deliberately excluded.
        exception_type = None if exception is None else type(exception).__name__
        self.event(
            "control_error",
            correlation=correlation,
            error_category=descriptor.category,
            diagnostic_code=descriptor.diagnostic_code,
            provider_status_category=exception_type,
            status_code=status_code,
        )


_CORRELATION: ContextVar[CorrelationIds] = ContextVar(
    "iprisk_control_correlation",
    default=CorrelationIds(),
)


def current_correlation() -> CorrelationIds:
    return _CORRELATION.get()


def bind_correlation(correlation: CorrelationIds) -> Token[CorrelationIds]:
    return _CORRELATION.set(correlation)


def reset_correlation(token: Token[CorrelationIds]) -> None:
    _CORRELATION.reset(token)


__all__ = [
    "CorrelationIds",
    "ErrorCategory",
    "PythonLoggingSink",
    "SafeErrorDescriptor",
    "SafeLogValueError",
    "StructuredEventSink",
    "StructuredLogger",
    "bind_correlation",
    "current_correlation",
    "reset_correlation",
]
