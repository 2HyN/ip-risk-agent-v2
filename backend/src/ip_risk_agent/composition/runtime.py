"""Small process-wide runtime primitives used by composition."""

from __future__ import annotations

import logging
import secrets
import sys
from datetime import UTC, datetime

_HANDLER_TAG = "iprisk_structured_stdout"


def configure_logging(level: str) -> None:
    """구조화 진단을 stdout 으로 내보낸다.

    ``StructuredLogger`` 는 ``ip_risk_agent.control`` 로거에 ``info()`` 로 JSON 을
    쓴다. 그런데 logging 설정이 없으면 root logger 기본 레벨이 WARNING 이라 그
    기록이 전부 조용히 버려진다. 배포에서 4xx 응답의 ``diagnostic_code`` 를 볼 수
    없어 원인을 매번 추측해야 했던 이유다.

    Cloud Run 은 stdout 을 수집하고 한 줄이 유효한 JSON 이면 구조화 필드로 읽는다.
    그래서 메시지 본문만 그대로 내보낸다. 같은 handler 를 중복으로 붙이지 않는다.
    """
    logger = logging.getLogger("ip_risk_agent")
    logger.setLevel(level)
    for handler in logger.handlers:
        if getattr(handler, "name", None) == _HANDLER_TAG:
            return
    handler = logging.StreamHandler(sys.stdout)
    handler.name = _HANDLER_TAG
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    # root 로 전파하면 uvicorn 포맷이 덧붙어 JSON 한 줄이 깨진다.
    logger.propagate = False


def utc_now() -> datetime:
    return datetime.now(UTC)


def opaque_id(kind: str) -> str:
    normalized = kind.strip().replace("_", "-")
    if not normalized:
        raise ValueError("opaque id kind must not be empty")
    return f"{normalized}-{secrets.token_urlsafe(24)}"


__all__ = ["configure_logging", "opaque_id", "utc_now"]
