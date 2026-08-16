from __future__ import annotations

import os
from uuid import uuid4

import pytest

firestore = pytest.importorskip("google.cloud.firestore_v1")
google_auth_credentials = pytest.importorskip("google.auth.credentials")

from ip_risk_agent.core.auth import User
from ip_risk_agent.persistence.core_firestore.repositories import (
    FirestoreControlUnitOfWorkFactory,
)
from ip_risk_agent.persistence.core_firestore.schema import USERS


@pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"),
    reason="FIRESTORE_EMULATOR_HOST is not configured",
)
def test_real_firestore_async_transaction_against_emulator() -> None:
    import asyncio
    from datetime import datetime, timezone

    async def scenario() -> None:
        suffix = uuid4().hex
        user_id = f"emulator-user-{suffix}"
        now = datetime.now(timezone.utc)
        client = firestore.AsyncClient(
            project=f"ip-risk-agent-test-{suffix}",
            credentials=google_auth_credentials.AnonymousCredentials(),
        )
        factory = FirestoreControlUnitOfWorkFactory.from_client(client)
        try:
            async with factory() as uow:
                await uow.users.add(
                    User(
                        user_id,
                        f"subject-{suffix}",
                        f"{suffix}@example.com",
                        "Emulator User",
                        now,
                        now,
                    )
                )
                await uow.commit()
            async with factory() as uow:
                assert await uow.users.get(user_id) is not None
        finally:
            await client.collection(USERS).document(user_id).delete()
            client.close()

    asyncio.run(scenario())
