from __future__ import annotations

import hashlib
import hmac

from ip_risk_agent.connectors.github.webhook import verify_webhook_signature


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_passes():
    body = b'{"action": "push"}'
    secret = "my-webhook-secret"
    signature = _sign(secret, body)
    assert verify_webhook_signature(body, signature, secret) is True


def test_wrong_secret_fails():
    body = b'{"action": "push"}'
    signature = _sign("correct-secret", body)
    assert verify_webhook_signature(body, signature, "wrong-secret") is False


def test_tampered_body_fails():
    body = b'{"action": "push"}'
    secret = "my-webhook-secret"
    signature = _sign(secret, body)
    tampered_body = b'{"action": "malicious"}'
    assert verify_webhook_signature(tampered_body, signature, secret) is False


def test_missing_signature_header_fails():
    assert verify_webhook_signature(b"body", None, "secret") is False


def test_malformed_signature_prefix_fails():
    assert verify_webhook_signature(b"body", "md5=deadbeef", "secret") is False
