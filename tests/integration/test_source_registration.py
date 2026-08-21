"""연결(Connection)과 감시 대상(Mount)의 경계 검증.

연결만 만들어진 상태에서 Mount 까지 만들어 버리면, 아무것도 감시하지 않는
Mount 가 목록에 "감시 중"으로 뜬다. 화면이 거짓을 말하고 대시보드 집계도
틀어진다. 그 상태가 다시 생기지 않게 잠근다.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from iprisk_contracts.common import SourceType

from ip_risk_agent.composition.source_callbacks import (
    ConnectionRegistry,
    DeviceRegistry,
    SourceRegistrationService,
)
from ip_risk_agent.core.common import stable_key


class RecordingBindings:
    """Firestore 바인딩 저장소의 인메모리 대역."""

    def __init__(self) -> None:
        self.connections: dict[str, dict] = {}
        self.mounts: list[dict] = []

    async def bind_connection(
        self,
        connection_id,
        *,
        source_type,
        risk_workspace_id,
        owner_user_id,
        connection_key,
        credential_ref=None,
        installation_id=None,
    ) -> None:
        self.connections[connection_id] = {
            "connection_id": connection_id,
            "source_type": source_type.value,
            "risk_workspace_id": risk_workspace_id,
            "owner_user_id": owner_user_id,
            "connection_key": connection_key,
            "credential_ref": credential_ref,
            "installation_id": installation_id,
        }

    async def bind_mount(
        self, mount_ref, *, connection_id, watch_channel_id=None, repository_full_name=None
    ) -> None:
        self.mounts.append(
            {
                "mount_id": mount_ref.mount_id,
                "connection_id": connection_id,
                "repository_full_name": repository_full_name,
            }
        )

    async def connection(self, connection_id: str) -> dict | None:
        return self.connections.get(connection_id)


class RecordingRegistrar:
    """Control 등록 콜백 대역. 무엇이 등록됐는지 그대로 남긴다."""

    def __init__(self) -> None:
        self.commands: list = []

    async def __call__(self, command):
        self.commands.append(command)

        class _Result:
            connection_id = stable_key(
                "source-connection",
                (command.source_type.value, command.connection_key),
            )
            source_workspace_id = "sws-1"
            mount_id = "mount-1"
            created_connection = True
            created_source_workspace = True
            created_mount = True

        return _Result()


def _request() -> Request:
    scope = {
        "type": "http",
        "headers": [],
        "session": {"iprisk_app_auth": {"user_id": "user-1", "session_version": 1}},
    }
    return Request(scope)


@pytest.fixture
def service():
    bindings = RecordingBindings()
    registrar = RecordingRegistrar()
    return (
        SourceRegistrationService(
            registrar,
            connections=ConnectionRegistry(store=bindings),
            devices=DeviceRegistry(),
            bindings=bindings,
        ),
        registrar,
        bindings,
    )


@pytest.mark.asyncio
async def test_connecting_github_does_not_create_a_mount(service) -> None:
    """App 설치만으로는 감시 대상이 없다. Mount 를 만들면 목록이 거짓말한다."""
    registration, registrar, bindings = service

    connection_id = await registration.create_github_connection(
        _request(), risk_workspace_id="vws-1", installation_id="155347373"
    )

    assert registrar.commands == [], "연결 단계에서 Control 에 등록하면 안 된다"
    assert bindings.connections[connection_id]["installation_id"] == "155347373"
    assert bindings.mounts == []


@pytest.mark.asyncio
async def test_connection_id_matches_what_control_will_derive(service) -> None:
    """미리 계산한 id 가 Control 의 값과 달라지면 두 기록이 갈라진다."""
    registration, registrar, _ = service

    connection_id = await registration.create_github_connection(
        _request(), risk_workspace_id="vws-1", installation_id="155347373"
    )
    await registration.create_github_mount(
        _request(),
        connection_id=connection_id,
        risk_workspace_id="vws-1",
        owner="Sora3780",
        repo="ip-risk-agent",
        tracked_branch="main",
    )

    command = registrar.commands[0]
    derived = stable_key(
        "source-connection", (command.source_type.value, command.connection_key)
    )
    assert derived == connection_id


@pytest.mark.asyncio
async def test_choosing_a_repository_registers_and_binds_it(service) -> None:
    """webhook 이 저장소 이름으로 Mount 를 되짚으려면 바인딩이 있어야 한다."""
    registration, registrar, bindings = service

    connection_id = await registration.create_github_connection(
        _request(), risk_workspace_id="vws-1", installation_id="155347373"
    )
    await registration.create_github_mount(
        _request(),
        connection_id=connection_id,
        risk_workspace_id="vws-1",
        owner="Sora3780",
        repo="ip-risk-agent",
        tracked_branch="main",
    )

    command = registrar.commands[0]
    assert command.external_scope_id == "Sora3780/ip-risk-agent@main"
    # alias 에는 경로 구분자를 넣을 수 없다. Control 이 거부한다.
    assert command.mount_alias == "Sora3780:ip-risk-agent (main)"
    assert bindings.mounts == [
        {
            "mount_id": "mount-1",
            "connection_id": connection_id,
            "repository_full_name": "Sora3780/ip-risk-agent",
        }
    ]


@pytest.mark.asyncio
async def test_a_cold_instance_still_finds_the_connection() -> None:
    """Cloud Run 은 인스턴스를 갈아치운다.

    프로세스 메모리에만 두면 연결을 만든 인스턴스와 저장소 목록을 묻는
    인스턴스가 달라졌을 때 방금 만든 연결이 "없는 연결"이 된다.
    """
    bindings = RecordingBindings()
    registrar = RecordingRegistrar()
    warm = SourceRegistrationService(
        registrar,
        connections=ConnectionRegistry(store=bindings),
        devices=DeviceRegistry(),
        bindings=bindings,
    )
    connection_id = await warm.create_github_connection(
        _request(), risk_workspace_id="vws-1", installation_id="155347373"
    )

    # 메모리를 잃은 새 인스턴스. 같은 Firestore 만 공유한다.
    cold_registry = ConnectionRegistry(store=bindings)

    assert await cold_registry.resolve_workspace(connection_id) == "vws-1"

    cold = SourceRegistrationService(
        registrar,
        connections=cold_registry,
        devices=DeviceRegistry(),
        bindings=bindings,
    )
    await cold.create_github_mount(
        _request(),
        connection_id=connection_id,
        risk_workspace_id="vws-1",
        owner="Sora3780",
        repo="ip-risk-agent",
        tracked_branch="main",
    )
    assert registrar.commands[0].connection_key == "github:155347373"


@pytest.mark.asyncio
async def test_an_unknown_connection_is_refused_with_a_clear_reason(service) -> None:
    """연결을 못 찾으면 무엇을 다시 해야 하는지 말해야 한다."""
    registration, _, _ = service

    with pytest.raises(Exception) as caught:
        await registration.create_github_mount(
            _request(),
            connection_id="source-connection:v1:missing",
            risk_workspace_id="vws-1",
            owner="Sora3780",
            repo="ip-risk-agent",
            tracked_branch="main",
        )
    assert "다시 시작" in str(getattr(caught.value, "detail", caught.value))


@pytest.mark.asyncio
async def test_drive_carries_its_credential_to_mount_registration(service) -> None:
    """등록을 미루면 자격증명 참조도 함께 미뤄진다. 잃어버리면 수집이 막힌다."""
    registration, registrar, _ = service

    from ip_risk_agent.connectors.common.credential_vault import CredentialRef

    connection_id = await registration.create_drive_connection(
        _request(),
        risk_workspace_id="vws-1",
        provider_subject="google-subject-1",
        provider_email="owner@example.com",
        credential_ref=CredentialRef(
            provider=SourceType.GOOGLE_DRIVE,
            connection_id="pending-state-1",
            secret_name="drive-oauth-token",
            key_id="drive-token-1",
        ),
    )
    assert registrar.commands == []

    await registration.create_drive_mount(
        _request(),
        connection_id=connection_id,
        risk_workspace_id="vws-1",
        selected_file_ids=["file-b", "file-a"],
    )

    command = registrar.commands[0]
    assert command.source_type is SourceType.GOOGLE_DRIVE
    assert command.credential_ref == "drive-token-1"
    # 선택 순서가 달라도 같은 Mount 로 수렴해야 재시도가 안전하다.
    assert command.external_scope_id == "file-a,file-b"


@pytest.mark.parametrize(
    "owner,repo,branch",
    [
        ("Sora3780", "ip-risk-agent", "main"),
        ("some-org", "deep.name", "release/2026"),
    ],
)
def test_mount_alias_is_a_single_path_segment(owner, repo, branch) -> None:
    """Control 은 alias 에 경로 구분자를 금지한다.

    provider 의 자연스러운 이름은 경로 모양이다(``owner/repo``). 그대로 넘기면
    등록이 422 로 막혀 저장소를 하나도 붙일 수 없다. Control 의 정규화 함수를
    그대로 불러 검사해, 두 쪽 규칙이 갈라지면 여기서 깨지게 한다.
    """
    from ip_risk_agent.composition.source_callbacks import _alias
    from ip_risk_agent.core.mounts.models import normalize_mount_alias

    alias = _alias(f"{owner}/{repo} ({branch})")
    assert normalize_mount_alias(alias) == alias
    assert owner in alias and repo in alias, "무엇을 감시하는지 알아볼 수 있어야 한다"


@pytest.mark.asyncio
async def test_registering_a_repository_produces_an_acceptable_alias(service) -> None:
    """실제 등록 경로가 만들어 내는 alias 도 Control 을 통과해야 한다."""
    from ip_risk_agent.core.mounts.models import normalize_mount_alias

    registration, registrar, _ = service
    connection_id = await registration.create_github_connection(
        _request(), risk_workspace_id="vws-1", installation_id="155363987"
    )
    await registration.create_github_mount(
        _request(),
        connection_id=connection_id,
        risk_workspace_id="vws-1",
        owner="Sora3780",
        repo="ip-risk-agent",
        tracked_branch="main",
    )
    alias = registrar.commands[0].mount_alias
    assert normalize_mount_alias(alias) == alias
