"""Defensive redaction and bounds for user-visible history projections."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from ip_risk_agent.application.security_gate import REDACTION_PLACEHOLDER, redact_text
from ip_risk_agent.core.common import DomainInvariantError

PATH_REDACTION_PLACEHOLDER = "[REDACTED_PATH]"
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)\b[A-Z]:[\\/][^\s,;]+")
_UNIX_ABSOLUTE_PATH = re.compile(
    r"(?<![:\w])/(?:Users|home|var|tmp|private|etc|mnt|opt)/[^\s,;]+"
)
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:access[_-]?key|api[_-]?key|authorization|client[_-]?secret|"
    r"credential|password|passwd|private[_-]?key|refresh[_-]?token|secret|token)"
)


@dataclass(frozen=True, slots=True)
class HistorySafetyPolicy:
    max_text_chars: int = 512
    max_items: int = 64
    max_depth: int = 5
    max_json_bytes: int = 8_192

    def __post_init__(self) -> None:
        for field_name in (
            "max_text_chars",
            "max_items",
            "max_depth",
            "max_json_bytes",
        ):
            if getattr(self, field_name) < 1:
                raise DomainInvariantError(
                    f"history_safety.{field_name} must be positive"
                )


class HistorySafetyError(DomainInvariantError):
    pass


def sanitize_history_text(value: str, policy: HistorySafetyPolicy) -> str:
    if "\x00" in value:
        raise HistorySafetyError("history text contains a NUL character")
    redacted, _ = redact_text(value.strip())
    redacted = _WINDOWS_ABSOLUTE_PATH.sub(PATH_REDACTION_PLACEHOLDER, redacted)
    redacted = _UNIX_ABSOLUTE_PATH.sub(PATH_REDACTION_PLACEHOLDER, redacted)
    return redacted[: policy.max_text_chars]


def sanitize_optional_history_text(
    value: str | None,
    policy: HistorySafetyPolicy,
) -> str | None:
    if value is None:
        return None
    sanitized = sanitize_history_text(value, policy)
    return sanitized or None


def sanitize_history_mapping(
    value: Mapping[str, object],
    policy: HistorySafetyPolicy,
) -> Mapping[str, object]:
    sanitized = _sanitize_mapping(value, policy, depth=0)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > policy.max_json_bytes:
        raise HistorySafetyError("history metadata exceeds the safe export limit")
    return sanitized


def _sanitize_mapping(
    value: Mapping[str, object],
    policy: HistorySafetyPolicy,
    *,
    depth: int,
) -> dict[str, object]:
    if depth >= policy.max_depth:
        raise HistorySafetyError("history metadata exceeds the nesting limit")
    if len(value) > policy.max_items:
        raise HistorySafetyError("history metadata has too many keys")
    output: dict[str, object] = {}
    for key in sorted(value):
        safe_key = sanitize_history_text(key, policy)
        if not safe_key:
            raise HistorySafetyError("history metadata key must not be empty")
        output[safe_key] = (
            REDACTION_PLACEHOLDER
            if _SENSITIVE_KEY.search(safe_key)
            else _sanitize_value(value[key], policy, depth=depth + 1)
        )
    return output


def _sanitize_value(
    value: object,
    policy: HistorySafetyPolicy,
    *,
    depth: int,
) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_history_text(value, policy)
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, policy, depth=depth)
    if isinstance(value, (list, tuple)):
        if depth >= policy.max_depth or len(value) > policy.max_items:
            raise HistorySafetyError("history metadata list exceeds the safe limit")
        return tuple(
            _sanitize_value(item, policy, depth=depth + 1) for item in value
        )
    raise HistorySafetyError("history metadata contains an unsupported value")


__all__ = [
    "HistorySafetyError",
    "HistorySafetyPolicy",
    "PATH_REDACTION_PLACEHOLDER",
    "sanitize_history_mapping",
    "sanitize_history_text",
    "sanitize_optional_history_text",
]
