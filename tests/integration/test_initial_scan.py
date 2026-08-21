"""Mount 생성 시 초기 스캔 검증.

파이프라인은 변경 이벤트에서 시작하므로, 연결 시점에 이미 있던 파일은
입구가 없다. 초기 스캔이 그 입구를 만든다 — "기획서가 있는 폴더를
연결했는데 아무 위험도 안 뜬다"는 상태가 다시 생기지 않게 잠근다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from iprisk_contracts.common import ChangeType, MountRef, SourceType

from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.composition.initial_scan import DriveInitialScanner


@dataclass
class FakeDriveFile:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None
    revision_id: str | None
    web_view_link: str | None = None


class FakeProvider:
    def __init__(self, files: dict[str, FakeDriveFile]) -> None:
        self._files = files
        self.exported = {"access_token": "refreshed"}

    def get_file(self, file_id: str) -> FakeDriveFile:
        if file_id not in self._files:
            raise NotFoundError(
                provider="google_drive", safe_message=f"missing {file_id}"
            )
        return self._files[file_id]

    def export_token(self) -> dict:
        return self.exported


class FakeVault:
    def __init__(self) -> None:
        self.stored = '{"access_token": "original"}'
        self.updates: list[str] = []

    async def get(self, ref: CredentialRef) -> str:
        return self.stored

    async def update(self, ref: CredentialRef, secret: str) -> None:
        self.updates.append(secret)


class FakeSink:
    def __init__(self) -> None:
        self.changes = []

    async def persist(self, change) -> None:
        self.changes.append(change)


CREDENTIAL = CredentialRef(
    provider=SourceType.GOOGLE_DRIVE,
    connection_id="conn-1",
    secret_name="drive-oauth-token",
    key_id="key-1",
)


class FakeLookup:
    async def resolve(self, mount_id: str):
        @dataclass
        class Context:
            connection_id: str
            credential_ref: CredentialRef

        return Context(connection_id="conn-1", credential_ref=CREDENTIAL)


MOUNT = MountRef(
    risk_workspace_id="vws-1",
    mount_id="mount-1",
    source_workspace_id="sws-1",
    source_type=SourceType.GOOGLE_DRIVE,
)


def scanner(files: dict[str, FakeDriveFile]) -> tuple[DriveInitialScanner, FakeSink, FakeVault]:
    sink = FakeSink()
    vault = FakeVault()
    provider = FakeProvider(files)
    instance = DriveInitialScanner(
        connection_lookup=FakeLookup(),
        credential_vault=vault,
        provider_factory=type("F", (), {"create": staticmethod(lambda token: provider)})(),
        change_sink=sink,
    )
    return instance, sink, vault


@pytest.mark.asyncio
async def test_existing_files_enter_the_pipeline_as_creates() -> None:
    instance, sink, _ = scanner(
        {
            "doc-1": FakeDriveFile("doc-1", "기획서.docx", "application/msword", "t1", "rev-1"),
            "doc-2": FakeDriveFile("doc-2", "라이선스.md", "text/markdown", "t2", "rev-2"),
        }
    )

    count = await instance.scan(MOUNT, ["doc-1", "doc-2"])

    assert count == 2
    assert [c.change_type for c in sink.changes] == [ChangeType.CREATE] * 2
    assert {c.artifact.display_name for c in sink.changes} == {"기획서.docx", "라이선스.md"}
    # 재시도해도 같은 fingerprint 여야 Control 의 idempotency 가 중복을 막는다.
    again, sink2, _ = scanner(
        {
            "doc-1": FakeDriveFile("doc-1", "기획서.docx", "application/msword", "t1", "rev-1"),
            "doc-2": FakeDriveFile("doc-2", "라이선스.md", "text/markdown", "t2", "rev-2"),
        }
    )
    await again.scan(MOUNT, ["doc-1", "doc-2"])
    assert [c.event_fingerprint for c in sink.changes] == [
        c.event_fingerprint for c in sink2.changes
    ]


@pytest.mark.asyncio
async def test_folders_are_skipped() -> None:
    """drive.file 스코프에서 폴더는 내용 접근이 함께 열리지 않는다."""
    instance, sink, _ = scanner(
        {
            "folder-1": FakeDriveFile(
                "folder-1", "자료", "application/vnd.google-apps.folder", None, None
            ),
            "doc-1": FakeDriveFile("doc-1", "기획서.docx", "application/msword", "t1", "rev-1"),
        }
    )

    count = await instance.scan(MOUNT, ["folder-1", "doc-1"])

    assert count == 1
    assert sink.changes[0].artifact.source_artifact_id == "doc-1"


@pytest.mark.asyncio
async def test_one_broken_file_does_not_block_the_rest() -> None:
    instance, sink, _ = scanner(
        {"doc-2": FakeDriveFile("doc-2", "살아있는 문서.md", "text/markdown", "t", "r")}
    )

    count = await instance.scan(MOUNT, ["doc-gone", "doc-2"])

    assert count == 1
    assert sink.changes[0].artifact.source_artifact_id == "doc-2"


@pytest.mark.asyncio
async def test_refreshed_token_is_persisted() -> None:
    """조회 중 갱신된 토큰을 버리면 다음 호출이 만료 토큰으로 시작한다."""
    instance, _, vault = scanner(
        {"doc-1": FakeDriveFile("doc-1", "기획서.docx", "application/msword", "t", "r")}
    )

    await instance.scan(MOUNT, ["doc-1"])

    assert vault.updates and "refreshed" in vault.updates[-1]


@pytest.mark.asyncio
async def test_scan_failure_does_not_fail_mount_creation() -> None:
    """Mount 는 이미 만들어진 사실이다. 스캔 실패가 그것을 뒤집으면 안 된다."""
    from ip_risk_agent.composition.source_callbacks import (
        ConnectionRegistry,
        DeviceRegistry,
        SourceRegistrationService,
    )
    from .test_source_registration import (
        RecordingBindings,
        RecordingRegistrar,
        _request,
    )

    class ExplodingScanner:
        async def scan(self, mount, selected_file_ids):
            raise RuntimeError("provider is down")

    bindings = RecordingBindings()
    service = SourceRegistrationService(
        RecordingRegistrar(),
        connections=ConnectionRegistry(store=bindings),
        devices=DeviceRegistry(),
        bindings=bindings,
        drive_scanner=ExplodingScanner(),
    )
    connection_id = await service.create_drive_connection(
        _request(),
        risk_workspace_id="vws-1",
        provider_subject="subject-1",
        provider_email="owner@example.com",
        credential_ref=CREDENTIAL,
    )

    result = await service.create_drive_mount(
        _request(),
        connection_id=connection_id,
        risk_workspace_id="vws-1",
        selected_file_ids=["doc-1"],
    )

    assert result.server_mount_id
