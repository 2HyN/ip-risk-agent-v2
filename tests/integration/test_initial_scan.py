"""Mount 생성 시 초기 스캔 검증.

파이프라인은 변경 이벤트에서 시작하므로, 연결 시점에 이미 있던 파일은
입구가 없다. 초기 스캔이 그 입구를 만든다 — "기획서가 있는 폴더를
연결했는데 아무 위험도 안 뜬다"는 상태가 다시 생기지 않게 잠근다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from iprisk_contracts.common import ChangeType

from ip_risk_agent.composition.drive_selection import ExpandedFile
from ip_risk_agent.composition.initial_scan import DriveInitialScanner


@dataclass
class FakeDriveFile:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None
    revision_id: str | None


class FakeSink:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.changes = []
        self._fail_for = fail_for or set()

    async def persist(self, change) -> None:
        if change.artifact.source_artifact_id in self._fail_for:
            raise RuntimeError("control rejected the change")
        self.changes.append(change)


def expanded(file_id: str, name: str, path: str, mime="text/markdown") -> ExpandedFile:
    return ExpandedFile(
        file=FakeDriveFile(file_id, name, mime, "2026-08-21T00:00:00Z", f"rev-{file_id}"),
        path=path,
    )


MOUNT = {
    "risk_workspace_id": "vws-1",
    "mount_id": "mount-1",
    "source_workspace_id": "sws-1",
}


@pytest.mark.asyncio
async def test_existing_files_enter_the_pipeline_as_creates() -> None:
    sink = FakeSink()
    scanner = DriveInitialScanner(change_sink=sink)

    count = await scanner.scan(
        **MOUNT,
        files=[
            expanded("doc-1", "requirements.txt", "1-blatant/requirements.txt"),
            expanded("doc-2", "requirements.txt", "2-partial/requirements.txt"),
        ],
    )

    assert count == 2
    assert [c.change_type for c in sink.changes] == [ChangeType.CREATE] * 2
    # 페르소나 폴더마다 같은 이름의 파일이 있다. 경로가 유일한 구분 정보다.
    assert [c.artifact.display_name for c in sink.changes] == [
        "1-blatant/requirements.txt",
        "2-partial/requirements.txt",
    ]


@pytest.mark.asyncio
async def test_fingerprints_are_deterministic_for_idempotent_retries() -> None:
    first_sink, second_sink = FakeSink(), FakeSink()
    files = [expanded("doc-1", "기획서.md", "docs/기획서.md")]

    await DriveInitialScanner(change_sink=first_sink).scan(**MOUNT, files=files)
    await DriveInitialScanner(change_sink=second_sink).scan(**MOUNT, files=files)

    assert (
        first_sink.changes[0].event_fingerprint
        == second_sink.changes[0].event_fingerprint
    )


@pytest.mark.asyncio
async def test_folders_are_skipped_defensively() -> None:
    """expander 가 걸렀어야 하지만, 빈 분석이 파이프라인에 들어가면 안 된다."""
    sink = FakeSink()

    count = await DriveInitialScanner(change_sink=sink).scan(
        **MOUNT,
        files=[
            expanded("folder-1", "자료", "자료", mime="application/vnd.google-apps.folder"),
            expanded("doc-1", "기획서.md", "기획서.md"),
        ],
    )

    assert count == 1
    assert sink.changes[0].artifact.source_artifact_id == "doc-1"


@pytest.mark.asyncio
async def test_one_rejected_file_does_not_block_the_rest() -> None:
    sink = FakeSink(fail_for={"doc-1"})

    count = await DriveInitialScanner(change_sink=sink).scan(
        **MOUNT,
        files=[
            expanded("doc-1", "막힌 문서.md", "막힌 문서.md"),
            expanded("doc-2", "살아있는 문서.md", "살아있는 문서.md"),
        ],
    )

    assert count == 1
    assert sink.changes[0].artifact.source_artifact_id == "doc-2"
