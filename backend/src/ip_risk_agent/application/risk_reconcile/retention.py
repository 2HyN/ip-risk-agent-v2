"""Minimal, deterministic retention helpers for analyzer evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from ip_risk_agent.application.security_gate.redaction import (
    REDACTION_PLACEHOLDER,
    redact_text,
)
from ip_risk_agent.core.common import DomainInvariantError

_SENSITIVE_METADATA_KEY = re.compile(
    r"(?i)(?:access[_-]?key|api[_-]?key|authorization|client[_-]?secret|"
    r"credential|password|passwd|private[_-]?key|refresh[_-]?token|secret|token)"
)


@dataclass(frozen=True, slots=True)
class EvidenceRetentionPolicy:
    max_excerpt_chars: int = 1_000
    max_reference_chars: int = 2_048
    max_metadata_chars: int = 256
    max_metadata_items: int = 32
    max_metadata_depth: int = 4
    max_metadata_json_bytes: int = 4_096
    max_summary_chars: int = 300
    # 설명과 권고는 Risk 한 줄 요약과 쓰임이 다르다. 어느 청구항이 문서의 어느
    # 부분과 어떻게 겹치는지를 적으므로 한 줄에 들어가지 않는다.
    max_explanation_chars: int = 800
    max_failure_message_chars: int = 512

    def __post_init__(self) -> None:
        for field_name in (
            "max_excerpt_chars",
            "max_reference_chars",
            "max_metadata_chars",
            "max_metadata_items",
            "max_metadata_depth",
            "max_metadata_json_bytes",
            "max_summary_chars",
            "max_explanation_chars",
            "max_failure_message_chars",
        ):
            if getattr(self, field_name) < 1:
                raise DomainInvariantError(f"evidence_retention.{field_name} must be positive")


def sanitize_excerpt(value: str, policy: EvidenceRetentionPolicy) -> str:
    redacted, _ = redact_text(value)
    return redacted[: policy.max_excerpt_chars]


def sanitize_reference(value: str, policy: EvidenceRetentionPolicy) -> str:
    reference = value.strip()
    if not reference:
        raise EvidenceRetentionError("evidence reference must not be empty")
    if "\x00" in reference or "\n" in reference or "\r" in reference or "\\" in reference:
        raise EvidenceRetentionError("evidence reference contains an unsafe path or control")
    if re.match(r"^[A-Za-z]:/", reference) or reference.startswith("/"):
        raise EvidenceRetentionError("local absolute evidence references are forbidden")
    redacted, _ = redact_text(reference)
    parsed = urlsplit(redacted)
    if parsed.scheme:
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            raise EvidenceRetentionError("unsupported evidence reference scheme")
        if parsed.username is not None or parsed.password is not None:
            raise EvidenceRetentionError("credential-bearing evidence reference is forbidden")
        redacted = urlunsplit(
            (parsed.scheme.casefold(), parsed.netloc, parsed.path, "", parsed.fragment)
        )
    return redacted[: policy.max_reference_chars]


def sanitize_metadata(
    value: Mapping[str, object], policy: EvidenceRetentionPolicy
) -> Mapping[str, object]:
    sanitized = _sanitize_mapping(value, policy, depth=0)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > policy.max_metadata_json_bytes:
        raise EvidenceRetentionError("evidence metadata exceeds retention limit")
    return sanitized


def sanitize_summary(value: str, policy: EvidenceRetentionPolicy) -> str:
    redacted, _ = redact_text(value.strip())
    summary = _clip(redacted, policy.max_summary_chars)
    if not summary:
        raise EvidenceRetentionError("risk summary must not be empty")
    return summary


def sanitize_explanation(value: str, policy: EvidenceRetentionPolicy) -> str:
    """설명과 권고를 다듬는다. 한 줄 요약보다 길이를 넉넉히 준다."""
    redacted, _ = redact_text(value.strip())
    explanation = _clip(redacted, policy.max_explanation_chars)
    if not explanation:
        raise EvidenceRetentionError("risk explanation must not be empty")
    return explanation


#: 문장이 끝난 자리. 닫는 따옴표와 괄호까지 함께 가져간다.
_SENTENCE_END = re.compile(r"[.!?][\s\"')\]]*")


def _clip(text: str, limit: int) -> str:
    """길이를 넘으면 **문장 경계에서** 자른다.

    글자 수로 끊으면 문장 한가운데서 멈춰, 읽는 사람에게 뜻이 다르게 전달된다.
    실제로 "…해당 특허 청구범위의 구성" 에서 끊긴 설명이 배포에 나갔다 — 정작
    무엇이 문제라는 것인지가 잘려 나간 자리에 있었다.

    잘라낼 문장 경계가 앞쪽에만 있으면 대부분을 버리게 되므로, 그때는 한도에서
    끊고 말줄임표로 **덜 왔다는 것을 보이게** 한다. 조용히 끊는 것보다 낫다.
    """
    text = text.rstrip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    boundaries = list(_SENTENCE_END.finditer(window))
    if boundaries and boundaries[-1].end() >= limit // 2:
        return window[: boundaries[-1].end()].rstrip()
    return window.rstrip() + "…"


def sanitize_failure_message(value: str, policy: EvidenceRetentionPolicy) -> str:
    redacted, _ = redact_text(value.strip())
    message = redacted[: policy.max_failure_message_chars]
    if not message:
        raise EvidenceRetentionError("provider failure safe_message must not be empty")
    return message


def _sanitize_mapping(
    value: Mapping[str, object],
    policy: EvidenceRetentionPolicy,
    *,
    depth: int,
) -> dict[str, object]:
    if depth >= policy.max_metadata_depth:
        raise EvidenceRetentionError("evidence metadata exceeds nesting limit")
    if len(value) > policy.max_metadata_items:
        raise EvidenceRetentionError("evidence metadata has too many keys")
    output: dict[str, object] = {}
    for key in sorted(value):
        safe_key = key.strip()
        if not safe_key or len(safe_key) > policy.max_metadata_chars:
            raise EvidenceRetentionError("evidence metadata key is invalid")
        output[safe_key] = (
            REDACTION_PLACEHOLDER
            if _SENSITIVE_METADATA_KEY.search(safe_key)
            else _sanitize_value(value[key], policy, depth=depth + 1)
        )
    return output


def _sanitize_value(
    value: object,
    policy: EvidenceRetentionPolicy,
    *,
    depth: int,
) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        redacted, _ = redact_text(value)
        return redacted[: policy.max_metadata_chars]
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, policy, depth=depth)
    if isinstance(value, (tuple, list)):
        if depth >= policy.max_metadata_depth:
            raise EvidenceRetentionError("evidence metadata exceeds nesting limit")
        if len(value) > policy.max_metadata_items:
            raise EvidenceRetentionError("evidence metadata list is too large")
        return [
            _sanitize_value(item, policy, depth=depth + 1)
            for item in value
        ]
    raise EvidenceRetentionError("evidence metadata contains an unsupported value")


class EvidenceRetentionError(DomainInvariantError):
    pass


__all__ = [
    "EvidenceRetentionError",
    "EvidenceRetentionPolicy",
    "sanitize_excerpt",
    "sanitize_failure_message",
    "sanitize_metadata",
    "sanitize_reference",
    "sanitize_summary",
]
