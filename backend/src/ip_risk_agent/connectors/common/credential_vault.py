"""SourceCredentialVault 계약(Protocol)과 개발/테스트용 가짜 구현.

Agent 2 Spec 6번(Credential Storage Port): credential 원문을 application DB에
저장하지 않는다. Production 구현(Secret Manager 연결)은 Integration Agent가
wiring 한다 (Master Spec 56/61번). 여기서는 설계도(Protocol)와 In-Memory
가짜 구현만 제공한다.
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import SourceType, StrictModel

from .errors import NotFoundError


class CredentialScope(StrictModel):
    """어떤 provider/connection의 어떤 비밀인지 나타내는 "주소".

    이 자체는 비밀이 아니다. 저장을 요청할 때만 쓴다.
    """

    provider: SourceType
    connection_id: str
    secret_name: str


class CredentialRef(StrictModel):
    """서랍에 넣고 돌려받는 "참조표". 실제 비밀 값은 절대 담지 않는다.

    로그나 shared contract(SourceChange 등)에 실어도 안전한 건 이 Ref뿐이다.
    """

    provider: SourceType
    connection_id: str
    secret_name: str
    key_id: str  # production에서는 Secret Manager resource name이 여기 들어갈 자리


class SourceCredentialVault(Protocol):
    """Agent 2 Spec 6번을 코드로 구체화한 Protocol."""

    async def put(self, scope: CredentialScope, secret: str) -> CredentialRef: ...

    async def get(self, ref: CredentialRef) -> str: ...

    async def delete(self, ref: CredentialRef) -> None: ...


class InMemoryCredentialVault:
    """개발/테스트 전용 가짜 서랍. 프로세스 재시작하면 다 사라진다.

    production에서는 절대 쓰지 않는다 — Integration Agent가 Secret
    Manager 기반 구현으로 교체한다.
    """

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

    async def delete(self, ref: CredentialRef) -> None:
        self._store.pop(ref.key_id, None)
