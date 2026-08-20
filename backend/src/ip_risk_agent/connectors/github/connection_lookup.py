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
