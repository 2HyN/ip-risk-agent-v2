"""Pending provider connection to canonical Control mount convergence."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from fastapi import HTTPException, Request
from iprisk_contracts import SourceType

from ip_risk_agent.application.public_facade import SourceMetadataRegistrationCommand
from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.github.mounts_routes import GitHubMountCreationResponse
from ip_risk_agent.connectors.google_drive.mounts_routes import DriveMountCreationResponse
from ip_risk_agent.core.common import normalize_utc, stable_key

from .source_auth import ConnectionAccess


class PendingConnectionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class PendingSourceConnection:
    id: str
    idempotency_key: str
    source_type: SourceType
    risk_workspace_id: str
    owner_user_id: str
    provider_subject: str
    provider_account_label: str | None
    credential_ref: CredentialRef | None
    installation_id: str | None
    status: PendingConnectionStatus
    created_at: datetime
    expires_at: datetime
    canonical_connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMountBinding:
    pending_connection_id: str
    canonical_connection_id: str
    source_workspace_id: str
    mount_id: str
    registration_key: str


class PendingConnectionStore(Protocol):
    async def get_pending(self, connection_id: str) -> PendingSourceConnection | None: ...
    async def get_pending_by_key(self, key: str) -> PendingSourceConnection | None: ...
    async def save_pending(self, value: PendingSourceConnection) -> None: ...
    async def get_binding(self, registration_key: str) -> SourceMountBinding | None: ...
    async def get_binding_for_mount(self, mount_id: str) -> SourceMountBinding | None: ...
    async def save_binding(self, value: SourceMountBinding) -> None: ...


class InMemoryPendingConnectionStore:
    """Test/local adapter; production uses the isolated GCP Firestore implementation."""

    def __init__(self) -> None:
        self.pending: dict[str, PendingSourceConnection] = {}
        self.by_key: dict[str, str] = {}
        self.bindings: dict[str, SourceMountBinding] = {}
        self.bindings_by_mount: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def get_pending(self, connection_id: str) -> PendingSourceConnection | None:
        return self.pending.get(connection_id)

    async def get_pending_by_key(self, key: str) -> PendingSourceConnection | None:
        connection_id = self.by_key.get(key)
        return self.pending.get(connection_id) if connection_id else None

    async def save_pending(self, value: PendingSourceConnection) -> None:
        self.pending[value.id] = value
        self.by_key[value.idempotency_key] = value.id

    async def get_binding(self, registration_key: str) -> SourceMountBinding | None:
        return self.bindings.get(registration_key)

    async def get_binding_for_mount(self, mount_id: str) -> SourceMountBinding | None:
        registration_key = self.bindings_by_mount.get(mount_id)
        return self.bindings.get(registration_key) if registration_key else None

    async def save_binding(self, value: SourceMountBinding) -> None:
        self.bindings[value.registration_key] = value
        self.bindings_by_mount[value.mount_id] = value.registration_key


class SourceRegistrationService:
    def __init__(
        self,
        *,
        store: PendingConnectionStore,
        control_facade,
        principal_resolver,
        clock: Callable[[], datetime],
        ttl: timedelta = timedelta(minutes=30),
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("pending connection TTL must be positive")
        self._store = store
        self._control = control_facade
        self._principal = principal_resolver
        self._clock = clock
        self._ttl = ttl
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(32))
        self._lock = getattr(store, "lock", asyncio.Lock())

    async def create_drive_connection(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        provider_subject: str,
        provider_email: str,
        credential_ref: CredentialRef,
    ) -> str:
        principal = await self._principal(request)
        return await self._create_pending(
            source_type=SourceType.GOOGLE_DRIVE,
            risk_workspace_id=risk_workspace_id,
            owner_user_id=principal.user.id,
            provider_subject=provider_subject,
            provider_account_label=provider_email,
            credential_ref=credential_ref,
            installation_id=None,
        )

    async def create_github_connection(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        installation_id: str,
    ) -> str:
        principal = await self._principal(request)
        return await self._create_pending(
            source_type=SourceType.GITHUB,
            risk_workspace_id=risk_workspace_id,
            owner_user_id=principal.user.id,
            provider_subject=installation_id,
            provider_account_label=None,
            credential_ref=None,
            installation_id=installation_id,
        )

    async def _create_pending(self, **values) -> str:
        now = normalize_utc(self._clock(), "pending_connection.clock")
        key = stable_key(
            "pending-source-connection-key",
            (
                values["source_type"].value,
                values["risk_workspace_id"],
                values["owner_user_id"],
                values["provider_subject"],
            ),
        )
        async with self._lock:
            existing = await self._store.get_pending_by_key(key)
            if existing and existing.status in {
                PendingConnectionStatus.PENDING,
                PendingConnectionStatus.ACTIVE,
            } and existing.expires_at > now:
                return existing.id
            pending = PendingSourceConnection(
                id=f"pending-{self._id_factory()}",
                idempotency_key=key,
                status=PendingConnectionStatus.PENDING,
                created_at=now,
                expires_at=now + self._ttl,
                **values,
            )
            await self._store.save_pending(pending)
            return pending.id

    async def resolve_connection_access(self, connection_id: str) -> ConnectionAccess:
        try:
            pending = await self._require_pending(connection_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="pending connection not found") from exc
        return ConnectionAccess(pending.risk_workspace_id, pending.owner_user_id)

    async def resolve_credential_ref(self, connection_id: str) -> CredentialRef:
        pending = await self._require_pending(connection_id, SourceType.GOOGLE_DRIVE)
        if pending.credential_ref is None:
            raise NotFoundError(provider="google_drive", safe_message="credential missing")
        return pending.credential_ref

    async def resolve_installation_id(self, connection_id: str) -> str:
        pending = await self._require_pending(connection_id, SourceType.GITHUB)
        if pending.installation_id is None:
            raise NotFoundError(provider="github", safe_message="installation missing")
        return pending.installation_id

    async def create_drive_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        selected_file_ids: list[str],
    ) -> DriveMountCreationResponse:
        if not selected_file_ids or len(selected_file_ids) != len(set(selected_file_ids)):
            raise HTTPException(status_code=422, detail="selected files must be unique and non-empty")
        scope = ",".join(sorted(selected_file_ids))
        registration = await self._mount(
            request,
            connection_id=connection_id,
            risk_workspace_id=risk_workspace_id,
            source_type=SourceType.GOOGLE_DRIVE,
            external_scope_id=f"drive-selection:{_digest(scope)}",
            display_name="Google Drive selection",
            mount_alias="Google Drive",
            tracking={"selected_file_ids": sorted(selected_file_ids)},
        )
        return DriveMountCreationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )

    async def create_github_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        owner: str,
        repo: str,
        tracked_branch: str,
    ) -> GitHubMountCreationResponse:
        external = f"{owner.lower()}/{repo.lower()}@{tracked_branch}"
        registration = await self._mount(
            request,
            connection_id=connection_id,
            risk_workspace_id=risk_workspace_id,
            source_type=SourceType.GITHUB,
            external_scope_id=external,
            display_name=f"{owner}/{repo}",
            mount_alias=repo,
            tracking={"owner": owner, "repo": repo, "branch": tracked_branch},
        )
        return GitHubMountCreationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )

    async def _mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        source_type: SourceType,
        external_scope_id: str,
        display_name: str,
        mount_alias: str,
        tracking: dict[str, object],
    ):
        principal = await self._principal(request)
        pending = await self._require_pending(connection_id, source_type)
        if pending.owner_user_id != principal.user.id or pending.risk_workspace_id != risk_workspace_id:
            raise HTTPException(status_code=403, detail="pending connection scope mismatch")
        registration_key = stable_key(
            "source-registration",
            (connection_id, risk_workspace_id, external_scope_id),
        )
        async with self._lock:
            binding = await self._store.get_binding(registration_key)
            if binding is not None:
                return _RegistrationView(binding.source_workspace_id, binding.mount_id)
            credential = (
                None
                if pending.credential_ref is None
                else f"{pending.credential_ref.provider.value}:{pending.credential_ref.key_id}"
            )
            result = await self._control.register_source_metadata(
                SourceMetadataRegistrationCommand(
                    registration_key=registration_key,
                    actor_user_id=principal.user.id,
                    risk_workspace_id=risk_workspace_id,
                    source_type=source_type,
                    connection_key=f"{source_type.value}:{pending.provider_subject}",
                    source_workspace_key=external_scope_id,
                    external_scope_id=external_scope_id,
                    source_workspace_display_name=display_name,
                    mount_alias=mount_alias,
                    provider_subject=pending.provider_subject,
                    provider_account_label=pending.provider_account_label,
                    credential_ref=credential,
                    tracking_config_safe=tracking,
                )
            )
            await self._store.save_binding(
                SourceMountBinding(
                    connection_id,
                    result.connection_id,
                    result.source_workspace_id,
                    result.mount_id,
                    registration_key,
                )
            )
            await self._store.save_pending(
                replace(
                    pending,
                    status=PendingConnectionStatus.ACTIVE,
                    canonical_connection_id=result.connection_id,
                )
            )
            return result

    async def _require_pending(
        self,
        connection_id: str,
        source_type: SourceType | None = None,
    ) -> PendingSourceConnection:
        pending = await self._store.get_pending(connection_id)
        if pending is None or (source_type is not None and pending.source_type is not source_type):
            raise NotFoundError(provider="source", safe_message="pending connection not found")
        now = normalize_utc(self._clock(), "pending_connection.clock")
        if pending.status in {PendingConnectionStatus.EXPIRED, PendingConnectionStatus.REVOKED}:
            raise HTTPException(status_code=410, detail="pending connection is unavailable")
        if pending.status is PendingConnectionStatus.PENDING and pending.expires_at <= now:
            await self._store.save_pending(replace(pending, status=PendingConnectionStatus.EXPIRED))
            raise HTTPException(status_code=410, detail="pending connection expired")
        return pending


@dataclass(frozen=True, slots=True)
class _RegistrationView:
    source_workspace_id: str
    mount_id: str


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "InMemoryPendingConnectionStore",
    "PendingConnectionStatus",
    "PendingConnectionStore",
    "PendingSourceConnection",
    "SourceMountBinding",
    "SourceRegistrationService",
]
