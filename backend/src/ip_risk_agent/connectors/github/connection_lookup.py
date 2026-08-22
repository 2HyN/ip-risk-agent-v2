"""mount_id -> installation_id 조회 포트.

Drive의 connection_lookup보다 단순하다 — installation_id는 비밀이 아니라
그냥 식별자라서 credential_vault를 거칠 필요가 없다. 앱 자체의 private key는
GitHubAppProviderFactory가 이미 앱 레벨로 들고 있다 (mount마다 다르지 않음).
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import StrictModel

from ..common.errors import NotFoundError


class GitHubConnectionContext(StrictModel):
    installation_id: str
    #: 이 mount 를 만든 연결. 같은 연결로 저장소를 **더** 붙일 때 필요하다.
    #: 저장소 하나를 붙인 뒤 다음 것을 붙이려면 연결을 다시 찾아야 하는데,
    #: 화면이 가진 것은 mount 뿐이다.
    operational_connection_id: str | None = None


class GitHubConnectionLookup(Protocol):
    async def resolve(self, mount_id: str) -> GitHubConnectionContext: ...


class InMemoryGitHubConnectionLookup:
    def __init__(self) -> None:
        self._mapping: dict[str, GitHubConnectionContext] = {}

    def register(self, mount_id: str, context: GitHubConnectionContext) -> None:
        self._mapping[mount_id] = context

    async def resolve(self, mount_id: str) -> GitHubConnectionContext:
        try:
            return self._mapping[mount_id]
        except KeyError as exc:
            raise NotFoundError(
                provider="github", safe_message=f"no installation registered for mount {mount_id}"
            ) from exc


class GitHubConnectionInstallationLookup(Protocol):
    """mount이 아니라 connection_id로 바로 installation_id를 찾는다.
    저장소 목록 조회처럼 아직 mount가 없는 단계에서 필요하다."""

    async def resolve_installation_id(self, connection_id: str) -> str: ...


class InMemoryGitHubConnectionInstallationLookup:
    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}

    def register(self, connection_id: str, installation_id: str) -> None:
        self._mapping[connection_id] = installation_id

    async def resolve_installation_id(self, connection_id: str) -> str:
        try:
            return self._mapping[connection_id]
        except KeyError as exc:
            raise NotFoundError(
                provider="github", safe_message=f"no installation registered for connection {connection_id}"
            ) from exc
