"""mount_id -> (connection_id, credential_ref) 조회 포트.

SourceChange/MountRef에는 어떤 Drive OAuth 계정을 써야 하는지가 없다 (그건
canonical WorkspaceMount/SourceConnection이 갖고 있고, Control Plane
소유다). Agent 2가 Control 내부를 직접 import할 수 없으므로, Integration이
이 Protocol을 canonical lookup에 연결해준다 (Agent 2 Spec 3번).
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import StrictModel

from ..common.credential_vault import CredentialRef
from ..common.errors import NotFoundError


class DriveConnectionContext(StrictModel):
    connection_id: str
    credential_ref: CredentialRef


class DriveConnectionLookup(Protocol):
    async def resolve(self, mount_id: str) -> DriveConnectionContext: ...


class InMemoryDriveConnectionLookup:
    """개발/테스트 전용 fake. mount_id -> context 매핑을 그대로 보관한다."""

    def __init__(self) -> None:
        self._mapping: dict[str, DriveConnectionContext] = {}

    def register(self, mount_id: str, context: DriveConnectionContext) -> None:
        self._mapping[mount_id] = context

    async def resolve(self, mount_id: str) -> DriveConnectionContext:
        try:
            return self._mapping[mount_id]
        except KeyError as exc:
            raise NotFoundError(
                provider="google_drive",
                safe_message=f"no connection registered for mount {mount_id}",
            ) from exc
