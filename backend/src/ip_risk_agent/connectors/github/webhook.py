"""GitHub webhook HMAC 서명 검증. dsdr-re/AI_develop_5(개인 저장소)의
services/github_client.py에서 이식 — provider-agnostic 순수 함수라 그대로 가져옴."""

from __future__ import annotations

import hashlib
import hmac


def verify_webhook_signature(payload_body: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)
