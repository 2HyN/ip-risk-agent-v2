"""Source 라우터의 생성 콜백을 Control canonical 등록으로 잇는다.

Agent 2 는 provider 식별자와 선택 결과만 넘기고, canonical
SourceConnection / SourceWorkspace / Mount 생성은 Control 이 한다
(docs/INTEGRATION.md 6절). 그 사이 변환이 여기 있다.

키 설계 원칙 — ``registration_key`` / ``connection_key`` / ``source_workspace_key``
는 재시도 동안 **같은 값**이어야 한다. Control 이 이 값을 deterministic canonical
ID 로 바꾸므로, 매번 새 값을 만들면 재시도마다 다른 Mount 가 생긴다
(docs/INTEGRATION.md 2절).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import HTTPException, Request, status
from iprisk_contracts.common import SourceType

from ip_risk_agent.core.common import stable_key
from ip_risk_agent.application.public_facade import (
    SourceMetadataRegistrationCallback,
    SourceMetadataRegistrationCommand,
)
from iprisk_contracts.common import MountRef

from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.github.mounts_routes import GitHubMountCreationResponse
from ip_risk_agent.connectors.google_drive.mounts_routes import (
    DriveMountCreationResponse,
)
from ip_risk_agent.connectors.local.routes import (
    MountRegistrationRequest,
    MountRegistrationResponse,
)

from .authz import current_user_id


class SourceBindingStore(Protocol):
    """Integration 소유 바인딩 저장소. 연결·Mount 를 provider 식별자로 되짚는다."""

    async def bind_connection(
        self,
        connection_id: str,
        *,
        source_type: SourceType,
        risk_workspace_id: str,
        owner_user_id: str,
        connection_key: str,
        credential_ref: CredentialRef | None = None,
        installation_id: str | None = None,
    ) -> None: ...

    async def bind_mount(
        self,
        mount_ref: MountRef,
        *,
        connection_id: str,
        watch_channel_id: str | None = None,
        repository_full_name: str | None = None,
    ) -> None: ...

    async def connection(self, connection_id: str) -> dict | None: ...


@dataclass
class ConnectionRegistry:
    """connection_id -> 연결 문맥.

    Control 은 connection 을 workspace 로 되짚는 공개 메서드를 두지 않았고,
    Agent 2 는 Control 내부를 import 할 수 없다. 그 틈을 Integration 이 메운다.
    connection 스코프 라우트의 authz 가 이 값을 쓴다.

    **프로세스 메모리만으로는 부족하다.** Cloud Run 은 인스턴스를 여러 개
    띄우고 수시로 재활용하므로, 연결을 만든 인스턴스와 저장소 목록을 묻는
    인스턴스가 다를 수 있다. 그러면 방금 만든 연결이 "없는 연결"이 된다.
    그래서 durable store 를 함께 둔다.
    """

    store: SourceBindingStore | None = None
    _context: dict[str, dict[str, Any]] = field(default_factory=dict)

    def remember(
        self,
        connection_id: str,
        *,
        risk_workspace_id: str,
        owner_user_id: str,
        connection_key: str | None = None,
        installation_id: str | None = None,
        credential_ref: CredentialRef | None = None,
    ) -> None:
        # 여기 담은 것이 durable store 보다 우선한다. 하나라도 빠뜨리면 그
        # 값은 프로세스가 살아 있는 동안 영영 보이지 않는다.
        self._context[connection_id] = {
            "connection_id": connection_id,
            "risk_workspace_id": risk_workspace_id,
            "owner_user_id": owner_user_id,
            "connection_key": connection_key,
            "installation_id": installation_id,
            "credential_ref": credential_ref,
        }

    async def context(self, connection_id: str) -> dict[str, Any] | None:
        local = self._context.get(connection_id)
        if local is not None:
            return local
        if self.store is None:
            return None
        return await self.store.connection(connection_id)

    async def resolve_workspace(self, connection_id: str) -> str | None:
        context = await self.context(connection_id)
        workspace_id = (context or {}).get("risk_workspace_id")
        return workspace_id if isinstance(workspace_id, str) else None


@dataclass
class DeviceRegistry:
    """device_id -> app_user 연결. 로컬 desktop 경로에서만 쓴다."""

    _user_by_device: dict[str, str] = field(default_factory=dict)
    _label_by_device: dict[str, str] = field(default_factory=dict)

    def remember(self, device_id: str, *, user_id: str, label: str) -> None:
        self._user_by_device[device_id] = user_id
        self._label_by_device[device_id] = label

    def user_of(self, device_id: str) -> str | None:
        return self._user_by_device.get(device_id)


def _credential_key(stored: object) -> str | None:
    """바인딩에 담긴 credential_ref 에서 Control 에 넘길 키를 꺼낸다.

    in-memory 경로에서는 ``CredentialRef`` 객체 그대로, Firestore 경로에서는
    직렬화된 dict 로 돌아온다.
    """
    if stored is None:
        return None
    if isinstance(stored, CredentialRef):
        return stored.key_id
    if isinstance(stored, dict):
        key_id = stored.get("key_id")
        return key_id if isinstance(key_id, str) and key_id else None
    return None


def _conflict(reason: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)


class SourceRegistrationService:
    """다섯 개 생성 콜백의 공통 구현.

    Agent 2 라우터들은 각자 다른 Protocol 을 기대하지만, 하는 일은 모두
    "provider 선택 결과를 canonical 등록 명령으로 바꿔 Control 에 넘긴다"로 같다.
    """

    def __init__(
        self,
        register_metadata: SourceMetadataRegistrationCallback,
        *,
        connections: ConnectionRegistry,
        devices: DeviceRegistry,
        bindings: SourceBindingStore | None = None,
    ) -> None:
        self._register = register_metadata
        self._connections = connections
        self._devices = devices
        self._bindings = bindings

    # ------------------------------------------------------------ 공통 도구

    async def _open_connection(
        self,
        *,
        source_type: SourceType,
        connection_key: str,
        risk_workspace_id: str,
        actor: str,
        credential_ref: CredentialRef | None = None,
        installation_id: str | None = None,
    ) -> str:
        """연결만 기록한다. Control 에는 아직 등록하지 않는다.

        Control 의 등록 명령은 ``mount_alias`` 와 ``external_scope_id`` 를 필수로
        요구한다. 연결 시점에는 무엇을 감시할지 아직 정해지지 않았으므로, 이때
        등록하면 ``pending`` scope 를 가진 Mount 가 만들어진다. 그 Mount 는
        아무것도 감시하지 않는데 목록에는 "감시 중"으로 보인다. 화면이 거짓을
        말하게 되므로 등록은 실제 감시 대상이 정해진 뒤로 미룬다.

        connection_id 는 Control 이 같은 입력에서 만들 값을 그대로 계산한다.
        그래야 나중에 등록해도 같은 연결로 수렴한다.
        """
        connection_id = stable_key(
            "source-connection", (source_type.value, connection_key)
        )
        if self._bindings is not None:
            await self._bindings.bind_connection(
                connection_id,
                source_type=source_type,
                risk_workspace_id=risk_workspace_id,
                owner_user_id=actor,
                connection_key=connection_key,
                credential_ref=credential_ref,
                installation_id=installation_id,
            )
        self._connections.remember(
            connection_id,
            risk_workspace_id=risk_workspace_id,
            owner_user_id=actor,
            connection_key=connection_key,
            installation_id=installation_id,
            credential_ref=credential_ref,
        )
        return connection_id

    async def _connection_key_of(self, connection_id: str) -> str:
        """Mount 등록에 쓸 provider 키. 없으면 연결부터 다시 해야 한다."""
        context = await self._connections.context(connection_id)
        connection_key = (context or {}).get("connection_key")
        if not isinstance(connection_key, str) or not connection_key:
            raise _conflict(
                "연결 정보를 찾을 수 없습니다. Source 연결을 다시 시작해 주세요."
            )
        return connection_key

    async def _bind_mount(
        self,
        registration,
        *,
        risk_workspace_id: str,
        source_type: SourceType,
        connection_id: str,
        repository_full_name: str | None = None,
    ) -> None:
        """webhook 이 provider 식별자로 Mount 를 되짚을 수 있게 기록한다.

        이것이 없으면 push 가 와도 어떤 Mount 인지 몰라 분석이 시작되지 않는다.
        """
        if self._bindings is None:
            return
        await self._bindings.bind_mount(
            MountRef(
                risk_workspace_id=risk_workspace_id,
                mount_id=registration.mount_id,
                source_workspace_id=registration.source_workspace_id,
                source_type=source_type,
            ),
            connection_id=connection_id,
            repository_full_name=repository_full_name,
        )

    # ---------------------------------------------------------------- Drive

    async def create_drive_connection(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        provider_subject: str,
        provider_email: str,
        credential_ref: CredentialRef,
    ) -> str:
        actor = current_user_id(request)
        # 연결 단계에서는 아직 추적 대상이 없다. Drive 계정 하나를 가리키는
        # 안정 키로 연결을 열어 두고, Control 등록과 Mount 는 파일 선택
        # 이후에 한다.
        return await self._open_connection(
            source_type=SourceType.GOOGLE_DRIVE,
            connection_key=f"google-drive:{provider_subject}",
            risk_workspace_id=risk_workspace_id,
            actor=actor,
            credential_ref=credential_ref,
        )

    async def create_drive_mount(
        self,
        request: Request,
        *,
        connection_id: str,
        risk_workspace_id: str,
        selected_file_ids: list[str],
    ) -> DriveMountCreationResponse:
        actor = current_user_id(request)
        if not selected_file_ids:
            raise _conflict("at least one Drive file must be selected")
        connection_key = await self._connection_key_of(connection_id)
        context = await self._connections.context(connection_id) or {}
        # 선택 집합이 같으면 재시도해도 같은 Mount 가 되도록 정렬해 키를 만든다.
        scope_id = ",".join(sorted(selected_file_ids))
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{risk_workspace_id}:{connection_id}:{scope_id}",
                actor_user_id=actor,
                risk_workspace_id=risk_workspace_id,
                source_type=SourceType.GOOGLE_DRIVE,
                connection_key=connection_key,
                source_workspace_key=f"{connection_id}:{scope_id}",
                external_scope_id=scope_id,
                source_workspace_display_name=(
                    f"Drive ({len(selected_file_ids)} items)"
                ),
                mount_alias=f"Drive ({len(selected_file_ids)} items)",
                credential_ref=_credential_key(context.get("credential_ref")),
                tracking_config_safe={
                    "selected_file_count": len(selected_file_ids)
                },
            )
        )
        await self._bind_mount(
            registration,
            risk_workspace_id=risk_workspace_id,
            source_type=SourceType.GOOGLE_DRIVE,
            connection_id=connection_id,
        )
        return DriveMountCreationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )

    # --------------------------------------------------------------- GitHub

    async def create_github_connection(
        self, request: Request, *, risk_workspace_id: str, installation_id: str
    ) -> str:
        actor = current_user_id(request)
        # App 설치는 "이 저장소들에 접근해도 좋다"까지만 정한다. 그중 무엇을
        # 감시할지는 아직 정해지지 않았으므로 Control 등록은 미룬다.
        return await self._open_connection(
            source_type=SourceType.GITHUB,
            connection_key=f"github:{installation_id}",
            risk_workspace_id=risk_workspace_id,
            actor=actor,
            installation_id=installation_id,
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
        actor = current_user_id(request)
        connection_key = await self._connection_key_of(connection_id)
        context = await self._connections.context(connection_id) or {}
        installation_id = context.get("installation_id")
        scope_id = f"{owner}/{repo}@{tracked_branch}"
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{risk_workspace_id}:{connection_id}:{scope_id}",
                actor_user_id=actor,
                risk_workspace_id=risk_workspace_id,
                source_type=SourceType.GITHUB,
                connection_key=connection_key,
                source_workspace_key=f"{connection_id}:{scope_id}",
                external_scope_id=scope_id,
                source_workspace_display_name=f"{owner}/{repo}",
                mount_alias=f"{owner}/{repo} ({tracked_branch})",
                provider_subject=installation_id if installation_id else None,
                provider_account_label=(
                    f"installation {installation_id}" if installation_id else None
                ),
                tracking_config_safe={"tracked_branch": tracked_branch},
            )
        )
        await self._bind_mount(
            registration,
            risk_workspace_id=risk_workspace_id,
            source_type=SourceType.GITHUB,
            connection_id=connection_id,
            repository_full_name=f"{owner}/{repo}",
        )
        return GitHubMountCreationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )

    # ---------------------------------------------------------------- Local

    async def register_device(
        self, request: Request, device_id: str, device_label: str
    ) -> None:
        actor = current_user_id(request)
        self._devices.remember(device_id, user_id=actor, label=device_label)

    async def create_local_mount(
        self, request: Request, body: MountRegistrationRequest
    ) -> MountRegistrationResponse:
        actor = current_user_id(request)
        owner = self._devices.user_of(body.device_id)
        if owner is not None and owner != actor:
            # 남의 기기를 자기 VWS 에 붙이지 못하게 한다.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="device belongs to a different user",
            )
        # canonical_root_path 는 요청 스키마에 없다(Agent 2 Spec 25).
        # 절대경로가 cloud metadata 로 나가지 않도록 device_id 만 스코프로 쓴다.
        scope_id = body.device_id
        registration = await self._register(
            SourceMetadataRegistrationCommand(
                registration_key=f"{body.risk_workspace_id}:local:{scope_id}",
                actor_user_id=actor,
                risk_workspace_id=body.risk_workspace_id,
                source_type=SourceType.LOCAL,
                connection_key=f"local:{scope_id}",
                source_workspace_key=f"local:{scope_id}",
                external_scope_id=scope_id,
                source_workspace_display_name=f"Local device {body.device_id}",
                mount_alias=f"Local device {body.device_id}",
                provider_subject=body.device_id,
                tracking_config_safe={
                    "include_pattern_count": len(body.include_patterns),
                    "exclude_pattern_count": len(body.exclude_patterns),
                },
            )
        )
        self._connections.remember(
            registration.connection_id,
            risk_workspace_id=body.risk_workspace_id,
            owner_user_id=actor,
        )
        return MountRegistrationResponse(
            server_mount_id=registration.mount_id,
            source_workspace_id=registration.source_workspace_id,
        )


__all__ = [
    "ConnectionRegistry",
    "DeviceRegistry",
    "SourceBindingStore",
    "SourceRegistrationService",
]
