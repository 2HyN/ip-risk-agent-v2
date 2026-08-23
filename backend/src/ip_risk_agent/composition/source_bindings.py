"""Provider-specific lookup views over Integration operational bindings."""

from __future__ import annotations

from iprisk_contracts import SourceType

from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.github.connection_lookup import GitHubConnectionContext
from ip_risk_agent.connectors.google_drive.connection_lookup import DriveConnectionContext


class DriveMountConnectionLookup:
    def __init__(self, store) -> None:
        self._store = store

    async def resolve(self, mount_id: str) -> DriveConnectionContext:
        binding = await self._store.get_binding_for_mount(mount_id)
        pending = (
            None
            if binding is None
            else await self._store.get_pending(binding.pending_connection_id)
        )
        # `credential_ref` 가 없다고 거절하지 않는다. OAuth 시절에는 자격증명 없는
        # Drive 연결이 곧 고장이었지만, D1 에서는 **없는 것이 정상**이다 — 접근이
        # 폴더 공유에서 오므로 보관할 자격증명이 아예 생기지 않는다. 이 조건이
        # 남아 있어 D1 마운트가 전부 초기 훑기에서 502 로 떨어졌다.
        if (
            binding is None
            or pending is None
            or pending.source_type is not SourceType.GOOGLE_DRIVE
        ):
            raise NotFoundError(
                provider="google_drive",
                safe_message="Drive mount connection binding was not found",
            )
        return DriveConnectionContext(
            connection_id=binding.canonical_connection_id,
            credential_ref=pending.credential_ref,
            operational_connection_id=binding.pending_connection_id,
        )


class GitHubMountConnectionLookup:
    def __init__(self, store) -> None:
        self._store = store

    async def resolve(self, mount_id: str) -> GitHubConnectionContext:
        binding = await self._store.get_binding_for_mount(mount_id)
        pending = (
            None
            if binding is None
            else await self._store.get_pending(binding.pending_connection_id)
        )
        if (
            pending is None
            or pending.source_type is not SourceType.GITHUB
            or pending.installation_id is None
        ):
            raise NotFoundError(
                provider="github",
                safe_message="GitHub mount connection binding was not found",
            )
        return GitHubConnectionContext(
            installation_id=pending.installation_id,
            operational_connection_id=(
                None if binding is None else binding.pending_connection_id
            ),
        )


__all__ = ["DriveMountConnectionLookup", "GitHubMountConnectionLookup"]
