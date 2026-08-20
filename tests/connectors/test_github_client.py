from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

jwt = pytest.importorskip("jwt")
pytest.importorskip("httpx")

from ip_risk_agent.connectors.github.client import (
    GitHubAppProvider,
    GitHubAppProviderFactory,
    build_app_jwt,
)


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    """테스트 전용 RSA 키 쌍을 그 자리에서 생성한다 (파일/외부 의존성 없음)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_pem, public_pem


def test_build_app_jwt_is_verifiable_with_public_key(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    token = build_app_jwt("app-123", private_pem)
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"], issuer="app-123")
    assert decoded["iss"] == "app-123"


def test_build_app_jwt_expiry_within_10_minutes(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    now = int(time.time())
    token = build_app_jwt("app-123", private_pem)
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"], issuer="app-123")
    assert decoded["exp"] - now <= 600
    assert decoded["iat"] <= now


def test_build_app_jwt_rejects_wrong_issuer_check(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    token = build_app_jwt("app-123", private_pem)
    with pytest.raises(jwt.InvalidIssuerError):
        jwt.decode(token, public_pem, algorithms=["RS256"], issuer="different-app")


def test_factory_creates_provider_with_installation_id(rsa_keypair):
    private_pem, _ = rsa_keypair
    factory = GitHubAppProviderFactory(app_id="app-123", private_key_pem=private_pem)
    provider = factory.create("installation-456")
    assert isinstance(provider, GitHubAppProvider)
