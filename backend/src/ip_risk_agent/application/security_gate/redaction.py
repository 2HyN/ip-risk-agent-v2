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


def redact_text(text: str, *, keyword_patterns: bool = True) -> tuple[str, int]:
    """비밀을 가린다. 두 갈래를 쓴다.

    * **모양으로 찾는 것** — PEM 블록, GitHub 토큰, JWT, ``Bearer``. 실제 비밀의 생김새를
      보므로 어디에 있든 맞다.
    * **이름으로 찾는 것** — ``secret``·``token``·``password`` 같은 낱말 뒤의 ``=`` 값.
      설정 파일의 "키 = 값" 을 전제한다.

    ``keyword_patterns=False`` 는 뒤쪽을 끈다. 의존성 파일에 쓴다.

    ## 왜 의존성 파일에서는 끄는가

    그 전제가 거기서 성립하지 않는다. 매니페스트의 왼쪽은 설정 키가 아니라 **패키지
    이름**이고, 이름에 저 낱말이 들어가는 패키지가 흔하다.

    ```
    tokenizers==0.15.0     → tokenizers=[REDACTED_SECRET]     버전을 잃는다
    secretstorage==3.3.3   → secretstorage=[REDACTED_SECRET]  버전을 잃는다
    "secret==1.0.0"        → "secret=[REDACTED_SECRET],       닫는 따옴표가 먹힌다
    ```

    ``tokenizers`` 는 HuggingFace 를 쓰는 거의 모든 프로젝트에 있고 ``secretstorage`` 는
    ``keyring`` 의 의존성이다. 드문 경우가 아니다.

    결과가 두 가지로 나빠진다. TOML·JSON 은 **파일 전체가 깨지고**, 줄 지향 형식은 버전을
    잃어 레지스트리 최신 버전의 라이선스로 판정된다 — 다른 라이선스를 그 버전의 것이라고
    **확정 기록**하는 것이다.

    모양으로 찾는 쪽은 그대로 둔다. 의존성 명세에 자격증명이 박힌 URL 이 들어올 수 있고
    (``pkg @ https://user:token@host/x.whl``), 그것은 이름이 아니라 생김새로 잡힌다.
    """
    redacted = text
    total = 0
    redacted, count = _PEM_PRIVATE_KEY.subn(REDACTION_PLACEHOLDER, redacted)
    total += count
    if keyword_patterns:
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


def redact_segments(
    segments: list[TextSegment], *, keyword_patterns: bool = True
) -> tuple[list[TextSegment], int]:
    output: list[TextSegment] = []
    total = 0
    for segment in segments:
        text, count = redact_text(segment.text, keyword_patterns=keyword_patterns)
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
