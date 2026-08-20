from __future__ import annotations

import asyncio

import pytest

from iprisk_contracts.common import SourceType
from ip_risk_agent.connectors.common.credential_vault import (
    CredentialRef,
    CredentialScope,
    InMemoryCredentialVault,
)
from ip_risk_agent.connectors.common.errors import NotFoundError


def test_update_replaces_stored_secret():
    async def scenario():
        vault = InMemoryCredentialVault()
        scope = CredentialScope(provider=SourceType.GOOGLE_DRIVE, connection_id="c1", secret_name="tok")
        ref = await vault.put(scope, "old-value")
        await vault.update(ref, "new-value")
        assert await vault.get(ref) == "new-value"

    asyncio.run(scenario())


def test_update_preserves_key_id():
    async def scenario():
        vault = InMemoryCredentialVault()
        scope = CredentialScope(provider=SourceType.GITHUB, connection_id="c1", secret_name="tok")
        ref = await vault.put(scope, "old-value")
        await vault.update(ref, "new-value")
        assert await vault.get(ref) == "new-value"

    asyncio.run(scenario())


def test_update_unknown_ref_raises_not_found():
    async def scenario():
        vault = InMemoryCredentialVault()
        fake_ref = CredentialRef(
            provider=SourceType.LOCAL, connection_id="c", secret_name="s", key_id="never-existed"
        )
        with pytest.raises(NotFoundError):
            await vault.update(fake_ref, "anything")

    asyncio.run(scenario())
