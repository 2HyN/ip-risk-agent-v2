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
    operational_connection_id: str | None = None
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


class DriveConnectionCredentialLookup(Protocol):
    """mount이 아니라 connection_id로 바로 credential을 찾는다. Picker
    세션처럼 아직 mount가 없는 단계(연결은 됐지만 어떤 파일을 추적할지
    아직 안 정한 상태)에서 필요하다."""

    async def resolve_credential_ref(self, connection_id: str) -> CredentialRef: ...


class InMemoryDriveConnectionCredentialLookup:
    """개발/테스트 전용 fake. connection_id -> credential_ref 매핑을 그대로 보관한다."""

    def __init__(self) -> None:
        self._mapping: dict[str, CredentialRef] = {}

    def register(self, connection_id: str, credential_ref: CredentialRef) -> None:
        self._mapping[connection_id] = credential_ref

    async def resolve_credential_ref(self, connection_id: str) -> CredentialRef:
        try:
            return self._mapping[connection_id]
        except KeyError as exc:
            raise NotFoundError(
                provider="google_drive",
                safe_message=f"no credential registered for connection {connection_id}",
            ) from exc
