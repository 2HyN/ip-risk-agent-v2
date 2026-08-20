"""SourceCredentialVault 계약(Protocol)과 개발/테스트용 가짜 구현.

Agent 2 Spec 6번(Credential Storage Port). update()는 Phase C에서 Drive
OAuth token 자동 갱신을 저장하기 위해 추가했다 (원래 Protocol에 없던
확장이지만 우리 소유 파일이라 자유롭게 진화 가능).
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import SourceType, StrictModel

from .errors import NotFoundError


class CredentialScope(StrictModel):
    provider: SourceType
    connection_id: str
    secret_name: str


class CredentialRef(StrictModel):
    provider: SourceType
    connection_id: str
    secret_name: str
    key_id: str


class SourceCredentialVault(Protocol):
    async def put(self, scope: CredentialScope, secret: str) -> CredentialRef: ...

    async def get(self, ref: CredentialRef) -> str: ...

    async def update(self, ref: CredentialRef, secret: str) -> None: ...

    async def delete(self, ref: CredentialRef) -> None: ...


class InMemoryCredentialVault:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._counter = 0

    async def put(self, scope: CredentialScope, secret: str) -> CredentialRef:
        self._counter += 1
        key_id = f"inmemory-{self._counter}"
        self._store[key_id] = secret
        return CredentialRef(
            provider=scope.provider,
            connection_id=scope.connection_id,
            secret_name=scope.secret_name,
            key_id=key_id,
        )

    async def get(self, ref: CredentialRef) -> str:
        try:
            return self._store[ref.key_id]
        except KeyError as exc:
            raise NotFoundError(
                provider=ref.provider.value,
                safe_message=f"credential not found for key_id={ref.key_id}",
            ) from exc

    async def update(self, ref: CredentialRef, secret: str) -> None:
        if ref.key_id not in self._store:
            raise NotFoundError(
                provider=ref.provider.value,
                safe_message=f"credential not found for key_id={ref.key_id}",
            )
        self._store[ref.key_id] = secret

    async def delete(self, ref: CredentialRef) -> None:
        self._store.pop(ref.key_id, None)
