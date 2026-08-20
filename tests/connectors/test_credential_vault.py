"""credential_vault.py의 Protocol/InMemory 구현을 확인한다.

pytest-asyncio 추가 설치 없이 돌아가도록 asyncio.run()으로 직접 감싼다.
"""

from __future__ import annotations

import asyncio

import pytest

from ip_risk_agent.connectors.common.credential_vault import (
    CredentialRef,
    CredentialScope,
    InMemoryCredentialVault,
)
from ip_risk_agent.connectors.common.errors import NotFoundError
from iprisk_contracts.common import SourceType


def test_put_then_get_roundtrip():
    async def scenario() -> None:
        vault = InMemoryCredentialVault()
        scope = CredentialScope(
            provider=SourceType.GITHUB, connection_id="conn-1", secret_name="installation_token"
        )
        ref = await vault.put(scope, "super-secret-value")
        value = await vault.get(ref)
        assert value == "super-secret-value"

    asyncio.run(scenario())


def test_ref_never_contains_secret_value():
    async def scenario() -> None:
        vault = InMemoryCredentialVault()
        scope = CredentialScope(
            provider=SourceType.GOOGLE_DRIVE, connection_id="conn-2", secret_name="refresh_token"
        )
        ref = await vault.put(scope, "1//super-secret-refresh-token")
        dumped = str(ref.model_dump())
        assert "1//super-secret-refresh-token" not in dumped

    asyncio.run(scenario())


def test_delete_then_get_raises_not_found():
    async def scenario() -> None:
        vault = InMemoryCredentialVault()
        scope = CredentialScope(provider=SourceType.LOCAL, connection_id="conn-3", secret_name="x")
        ref = await vault.put(scope, "value")
        await vault.delete(ref)
        with pytest.raises(NotFoundError):
            await vault.get(ref)

    asyncio.run(scenario())


def test_get_unknown_ref_raises_not_found():
    async def scenario() -> None:
        vault = InMemoryCredentialVault()
        fake_ref = CredentialRef(
            provider=SourceType.GITHUB, connection_id="c", secret_name="s", key_id="never-existed"
        )
        with pytest.raises(NotFoundError):
            await vault.get(fake_ref)

    asyncio.run(scenario())


def test_different_puts_get_different_key_ids():
    async def scenario() -> None:
        vault = InMemoryCredentialVault()
        scope = CredentialScope(provider=SourceType.GITHUB, connection_id="c", secret_name="s")
        ref1 = await vault.put(scope, "value1")
        ref2 = await vault.put(scope, "value2")
        assert ref1.key_id != ref2.key_id
        assert await vault.get(ref1) == "value1"
        assert await vault.get(ref2) == "value2"

    asyncio.run(scenario())


def test_multiple_providers_isolated_by_scope():
    async def scenario() -> None:
        vault = InMemoryCredentialVault()
        drive_scope = CredentialScope(
            provider=SourceType.GOOGLE_DRIVE,
            connection_id="research@company.com",
            secret_name="refresh_token",
        )
        github_scope = CredentialScope(
            provider=SourceType.GITHUB, connection_id="installation-1", secret_name="private_key"
        )
        drive_ref = await vault.put(drive_scope, "drive-secret")
        github_ref = await vault.put(github_scope, "github-secret")
        assert await vault.get(drive_ref) == "drive-secret"
        assert await vault.get(github_ref) == "github-secret"

    asyncio.run(scenario())
