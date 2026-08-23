"""mount_id -> connection_id 조회 포트.

D1 이후 이 조회가 자격증명을 들고 오지 않는다. Drive 접근은 폴더 공유에서 오고
신원은 하나뿐이라, 마운트마다 고를 토큰이 없다. 그래도 연결 자체는 찾아야 한다 —
**변경 커서를 연결 id 로 보관**하기 때문이다.

`credential_ref` 칸은 남겨 두되 비어 있을 수 있다. 서비스 계정 연결에는 보관한
자격증명이 없다.
"""
from __future__ import annotations
from typing import Protocol
from iprisk_contracts.common import StrictModel
from ..common.credential_vault import CredentialRef
from ..common.errors import NotFoundError
class DriveConnectionContext(StrictModel):
    connection_id: str
    #: D1 연결에는 없다. 보관할 자격증명이 없는 것이 요점이다.
    credential_ref: CredentialRef | None = None
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
