"""owner/repo -> 이 저장소를 추적 중인 mount 목록 조회 포트.

여러 VWS가 같은 저장소를 서로 다른 mount로 각자 추적할 수 있다(Master
Spec §63). 이 조회는 Control Plane의 canonical WorkspaceMount 데이터를
알아야 하므로, ConnectionLookup류와 같은 성격의 Integration wiring point다.
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import MountRef


class GitHubMountResolver(Protocol):
    async def resolve_mounts(self, owner: str, repo: str) -> list[MountRef]: ...


class InMemoryGitHubMountResolver:
    def __init__(self) -> None:
        self._mapping: dict[tuple[str, str], list[MountRef]] = {}

    def register(self, owner: str, repo: str, mounts: list[MountRef]) -> None:
        self._mapping[(owner, repo)] = mounts

    async def resolve_mounts(self, owner: str, repo: str) -> list[MountRef]:
        return self._mapping.get((owner, repo), [])
