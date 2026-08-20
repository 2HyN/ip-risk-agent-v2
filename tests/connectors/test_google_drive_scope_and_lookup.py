from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from iprisk_contracts.common import SourceType
from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.google_drive.connection_lookup import (
    DriveConnectionContext,
    InMemoryDriveConnectionLookup,
)
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope


def test_tracking_scope_contains_true_for_selected_file():
    scope = DriveTrackingScope(mount_id="m1", selected_file_ids=["f1", "f2"])
    assert scope.contains("f1") is True


def test_tracking_scope_contains_false_for_unselected_file():
    scope = DriveTrackingScope(mount_id="m1", selected_file_ids=["f1"])
    assert scope.contains("f2") is False


def test_tracking_scope_display_metadata_defaults_empty():
    scope = DriveTrackingScope(mount_id="m1", selected_file_ids=[])
    assert scope.display_metadata_by_file == {}


def test_tracking_scope_rejects_unknown_field():
    with pytest.raises(ValidationError):
        DriveTrackingScope(mount_id="m1", selected_file_ids=[], not_real="x")  # type: ignore[call-arg]


def test_connection_lookup_register_then_resolve():
    async def scenario():
        lookup = InMemoryDriveConnectionLookup()
        ref = CredentialRef(
            provider=SourceType.GOOGLE_DRIVE, connection_id="c1", secret_name="s", key_id="k1"
        )
        context = DriveConnectionContext(connection_id="c1", credential_ref=ref)
        lookup.register("mount-1", context)

        resolved = await lookup.resolve("mount-1")
        assert resolved.connection_id == "c1"

    asyncio.run(scenario())


def test_connection_lookup_unknown_mount_raises_not_found():
    async def scenario():
        lookup = InMemoryDriveConnectionLookup()
        with pytest.raises(NotFoundError):
            await lookup.resolve("never-registered")

    asyncio.run(scenario())
