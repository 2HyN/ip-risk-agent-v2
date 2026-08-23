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

    async def get_bindings_for_connection(

        self, canonical_connection_id: str

    ) -> tuple[SourceMountBinding, ...]: ...

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



    async def get_bindings_for_connection(

        self, canonical_connection_id: str

    ) -> tuple[SourceMountBinding, ...]:

        return tuple(

            binding

            for binding in self.bindings.values()

            if binding.canonical_connection_id == canonical_connection_id

        )



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

            if existing and existing.status is PendingConnectionStatus.ACTIVE:

                # ACTIVE connections are durable. A later OAuth callback is an

                # explicit reauthorization and refreshes the credential on the

                # existing operational handle rather than creating a parallel

                # connection for the same account/workspace.

                refreshed = replace(

                    existing,

                    provider_account_label=values["provider_account_label"],

                    credential_ref=values["credential_ref"],

                )

                await self._store.save_pending(refreshed)

                return refreshed.id

            if (

                existing

                and existing.status is PendingConnectionStatus.PENDING

                and existing.expires_at > now

            ):

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

            raise HTTPException(

                status_code=422,

                detail="selected files must be unique and non-empty",

            )

        pending = await self._require_pending(connection_id, SourceType.GOOGLE_DRIVE)

        principal = await self._principal(request)

        if (

            pending.owner_user_id != principal.user.id

            or pending.risk_workspace_id != risk_workspace_id

        ):

            raise HTTPException(status_code=403, detail="pending connection scope mismatch")

        normalized_file_ids = sorted(selected_file_ids)



        # Source workspace 의 정체성은 **공유받은 폴더**다 (D1).
        #
        # 예전에는 연결된 Drive **계정**이었다. 사용자 OAuth 시절에는 그것이 실제로
        # 마운트를 갈라 주는 값이었다 — 계정이 다르면 다른 마운트였다. D1 이 신원을
        # 서비스 계정 하나로 바꾸면서 그 값이 **모든 사용자·모든 폴더에 대해 같아졌다.**
        # 계정을 정체성으로 두면 한 워크스페이스의 Drive 폴더가 전부 마운트 하나로
        # 접히고, 두 번째 폴더를 붙이는 순간 첫 폴더가 조용히 추적에서 빠진다 —
        # 추적 범위의 `folder_id` 는 하나뿐이라 덮어써지기 때문이다.
        #
        # 그래서 폴더 id 를 쓴다. GitHub 이 `owner/repo@branch` 라는 안정된 정체성을
        # 쓰는 것과 같은 자리이고, 폴더가 곧 마운트 단위라는 §6.1 과도 맞는다.
        #
        # 두 키 모두 `risk_workspace_id` 를 품는다. 그래서 **서로 다른 워크스페이스가
        # 같은 폴더를 추적해도 각자의 마운트·커서·감시 채널을 갖는다** — 워크스페이스는
        # 서로 완전히 독립이라는 D7 이 여기서 지켜진다.
        folder_id = pending.provider_subject
        external_scope_id = f"drive-folder:{folder_id}"
        registration_scope = f"{SourceType.GOOGLE_DRIVE.value}:{folder_id}"
        registration_key = stable_key(

            "source-registration",

            (registration_scope, risk_workspace_id, external_scope_id),

        )



        tracked_file_ids = await self._tracked_drive_file_ids(registration_key)

        new_file_ids = [

            file_id for file_id in normalized_file_ids if file_id not in tracked_file_ids

        ]

        if not new_file_ids:

            # 요청한 파일이 이미 전부 추적 중이다. 같은 요청의 재시도와 구별되지

            # 않으므로 오류가 아니라 **멱등 응답**으로 끝낸다. 아무것도 실패하지

            # 않았고 canonical 상태도 그대로다.

            binding = await self._store.get_binding(registration_key)

            if binding is None:  # 추적 중인데 binding 이 없을 수는 없다.

                raise HTTPException(

                    status_code=409, detail="selected files are already tracked"

                )

            return DriveMountCreationResponse(

                server_mount_id=binding.mount_id,

                source_workspace_id=binding.source_workspace_id,

                selected_file_ids=normalized_file_ids,

            )



        merged_file_ids = sorted(tracked_file_ids | set(normalized_file_ids))

        registration = await self._mount(

            request,

            connection_id=pending.id,

            registration_scope=registration_scope,

            risk_workspace_id=risk_workspace_id,

            source_type=SourceType.GOOGLE_DRIVE,

            external_scope_id=external_scope_id,

            display_name=_drive_display_name(pending),

            mount_alias=_drive_mount_alias(pending),

            tracking={"selected_file_ids": merged_file_ids},

        )

        return DriveMountCreationResponse(

            server_mount_id=registration.mount_id,

            source_workspace_id=registration.source_workspace_id,

            # 이번에 새로 추가된 것만 돌려준다. 초기 스캔이 이미 분석한 파일을

            # 다시 훑지 않도록 하는 경계다.

            selected_file_ids=new_file_ids,

        )



    async def _tracked_drive_file_ids(self, registration_key: str) -> set[str]:

        """이 Drive 계정 source workspace 가 현재 추적 중인 file id 집합."""

        binding = await self._store.get_binding(registration_key)

        if binding is None:

            return set()

        context = await self._control.get_source_workspace_context(

            binding.source_workspace_id

        )

        values = context.tracking_config_safe.get("selected_file_ids", ())

        if not isinstance(values, (list, tuple)):

            return set()

        return {value for value in values if isinstance(value, str)}



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

        registration_scope: str | None = None,

    ):

        principal = await self._principal(request)

        pending = await self._require_pending(connection_id, source_type)

        if pending.owner_user_id != principal.user.id or pending.risk_workspace_id != risk_workspace_id:

            raise HTTPException(status_code=403, detail="pending connection scope mismatch")

        # 기본은 pending connection 기준이다. 재연결해도 같은 canonical source 로

        # 수렴해야 하는 provider 는 계정 기준 scope 를 넘긴다.

        registration_key = stable_key(

            "source-registration",

            (registration_scope or connection_id, risk_workspace_id, external_scope_id),

        )

        async with self._lock:

            # 기존 binding 이 있어도 Control 재등록을 건너뛰지 않는다. 등록 키가

            # 계정 단위로 안정적이므로, 건너뛰면 넓어진 추적 범위가 canonical 쪽에

            # 영원히 반영되지 않는다. register_source_metadata 는 멱등이며 바뀐 것이

            # 없으면 쓰기도 audit 도 남기지 않는다.

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

                    # source workspace 는 mount 를 하나만 가진다(전역 제약). 따라서

                    # 정체성이 VWS 범위여야 한다. provider 쪽 scope 는 그대로 두고

                    # 레코드 키만 VWS 로 한정한다 — 같은 Drive 계정이나 같은 GitHub

                    # repository 를 서로 다른 Risk Workspace 에 연결하는 것은 정상이다.

                    source_workspace_key=f"vws:{risk_workspace_id}|scope:{external_scope_id}",

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





def _drive_display_name(pending: PendingSourceConnection) -> str:

    """연결된 Drive 계정을 가리키는 이름. 계정당 하나로 안정적이다."""

    return pending.provider_account_label or "Google Drive"





def _drive_mount_alias(pending: PendingSourceConnection) -> str:

    """VWS 안에서 유일하고 사람이 읽을 수 있는 alias — **폴더 이름 그대로**.

    D1 에서 라벨은 공유받은 폴더의 이름이다. GitHub 이 repo 이름을 그대로 쓰는
    것과 같은 자리이고, 소스 종류는 화면이 따로 표시하므로 "Google Drive " 접두사는
    이름을 길게만 만들었다. 라벨이 없으면 폴더 id digest 로 안정된 값을 만든다.

    """

    label = pending.provider_account_label

    if label:

        return label

    return f"Google Drive {_digest(pending.provider_subject)[:8]}"

