"""Deterministic best-effort secret redaction for transient text segments."""

from __future__ import annotations

import re

from iprisk_contracts import TextSegment

REDACTION_PLACEHOLDER = "[REDACTED_SECRET]"

_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----.*?"
    r"-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    re.DOTALL,
)
_SENSITIVE_KEY = (
    r"(?:access[_-]?key|api[_-]?key|authorization|client[_-]?secret|"
    r"credential|password|passwd|private[_-]?key|refresh[_-]?token|secret|token)"
)
_ENV_SECRET_LINE = re.compile(
    rf"(?im)^(?P<prefix>\s*(?:export\s+)?[A-Z0-9_]*{_SENSITIVE_KEY}[A-Z0-9_]*\s*=\s*)"
    r"(?!\[REDACTED_SECRET\]\s*$)(?P<value>[^\r\n]*)$"
)
_QUOTED_ASSIGNMENT = re.compile(
    rf"(?i)(?P<prefix>[\"']?{_SENSITIVE_KEY}[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?!\[REDACTED_SECRET\])(?P<value>.*?)(?P=quote)"
)
_UNQUOTED_ASSIGNMENT = re.compile(
    rf"(?i)(?P<prefix>\b{_SENSITIVE_KEY}\b\s*[:=]\s*)"
    r"(?P<value>(?!\[REDACTED_SECRET\])[^\s,;}}#]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+(?!\[REDACTED_SECRET\])[A-Za-z0-9._~+/=-]{8,}")
_GITHUB_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


def redact_text(text: str) -> tuple[str, int]:
    redacted = text
    total = 0
    redacted, count = _PEM_PRIVATE_KEY.subn(REDACTION_PLACEHOLDER, redacted)
    total += count
    redacted, count = _ENV_SECRET_LINE.subn(
        lambda match: f"{match.group('prefix')}{REDACTION_PLACEHOLDER}",
        redacted,
    )
    total += count
    redacted, count = _QUOTED_ASSIGNMENT.subn(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{REDACTION_PLACEHOLDER}{match.group('quote')}"
        ),
        redacted,
    )
    total += count
    redacted, count = _UNQUOTED_ASSIGNMENT.subn(
        lambda match: f"{match.group('prefix')}{REDACTION_PLACEHOLDER}",
        redacted,
    )
    total += count
    redacted, count = _BEARER_TOKEN.subn(
        f"Bearer {REDACTION_PLACEHOLDER}", redacted
    )
    total += count
    redacted, count = _GITHUB_TOKEN.subn(REDACTION_PLACEHOLDER, redacted)
    total += count
    redacted, count = _JWT.subn(REDACTION_PLACEHOLDER, redacted)
    total += count
    return redacted, total


def redact_segments(segments: list[TextSegment]) -> tuple[list[TextSegment], int]:
    output: list[TextSegment] = []
    total = 0
    for segment in segments:
        text, count = redact_text(segment.text)
        total += count
        output.append(
            TextSegment(
                segment_id=segment.segment_id,
                text=text,
                line_start=segment.line_start,
                line_end=segment.line_end,
                segment_kind=segment.segment_kind,
            )
        )
    return output, total


__all__ = ["REDACTION_PLACEHOLDER", "redact_segments", "redact_text"]
