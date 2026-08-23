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


def test_tracking_scope_holds_a_folder_not_a_list_of_files():
    """추적 대상은 **명단**이 아니라 폴더다 (§6.1 · 1-F).

    명단이면 마운트한 뒤에 폴더에 넣은 파일이 영영 잡히지 않는다 — 변경 피드에는
    오는데 명단에 없다고 버려진다. v1 이 그렇게 실패했고, 이 서비스를 쓰는 방법이
    바로 그 "폴더에 넣는 것" 이다.
    """
    scope = DriveTrackingScope(mount_id="m1", folder_id="folder-1")
    assert scope.folder_id == "folder-1"
    assert not hasattr(scope, "selected_file_ids")


def test_membership_is_asked_of_the_provider_not_the_scope():
    """소속은 **지금 어디에 있는지**를 묻는 것이라 모델이 혼자 답할 수 없다.

    그래서 `contains` 가 없어졌다. 있으면 옛 명단 방식이 조용히 되살아난다.
    """
    scope = DriveTrackingScope(mount_id="m1", folder_id="folder-1")
    assert not hasattr(scope, "contains")


def test_tracking_scope_display_metadata_defaults_empty():
    scope = DriveTrackingScope(mount_id="m1", folder_id="folder-1")
    assert scope.display_metadata_by_file == {}


def test_tracking_scope_rejects_unknown_field():
    with pytest.raises(ValidationError):
        DriveTrackingScope(mount_id="m1", folder_id="f", not_real="x")  # type: ignore[call-arg]


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
