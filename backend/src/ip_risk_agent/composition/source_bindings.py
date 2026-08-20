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
        if (
            binding is None
            or pending is None
            or pending.source_type is not SourceType.GOOGLE_DRIVE
            or pending.credential_ref is None
        ):
            raise NotFoundError(
                provider="google_drive",
                safe_message="Drive mount connection binding was not found",
            )
        return DriveConnectionContext(
            connection_id=binding.canonical_connection_id,
            credential_ref=pending.credential_ref,
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
        return GitHubConnectionContext(installation_id=pending.installation_id)


__all__ = ["DriveMountConnectionLookup", "GitHubMountConnectionLookup"]
