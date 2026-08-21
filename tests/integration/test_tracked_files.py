"""감시 파일 목록 라우트 검증.

추적 스코프는 Integration 소유라 Control API 로는 보이지 않는다. 이 라우트가
없으면 사용자는 폴더를 연결한 뒤 어떤 파일이 인식됐는지 확인할 길이 없다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from iprisk_contracts.common import MountRef, SourceType

from ip_risk_agent.composition.tracked_files import create_tracked_files_router


@dataclass
class DriveScope:
    selected_file_ids: list
    display_metadata_by_file: dict


@dataclass
class GithubScope:
    owner: str
    repo: str
    tracked_branch: str


class FakeStore:
    def __init__(self, scopes: dict) -> None:
        self._scopes = scopes

    async def load(self, mount_id: str):
        return self._scopes.get(mount_id)


MOUNTS = {
    "mount-drive": MountRef(
        risk_workspace_id="vws-1",
        mount_id="mount-drive",
        source_workspace_id="sws-1",
        source_type=SourceType.GOOGLE_DRIVE,
    ),
    "mount-github": MountRef(
        risk_workspace_id="vws-1",
        mount_id="mount-github",
        source_workspace_id="sws-2",
        source_type=SourceType.GITHUB,
    ),
}


async def resolve_mount(mount_id: str) -> MountRef:
    return MOUNTS[mount_id]


def build_client(*, authz_calls: list | None = None) -> TestClient:
    async def authz(request, resource_id: str) -> None:
        if authz_calls is not None:
            authz_calls.append(resource_id)

    app = FastAPI()
    app.include_router(
        create_tracked_files_router(
            mount_ref_resolver=resolve_mount,
            authz_dependency=authz,
            drive_scope_store=FakeStore(
                {
                    "mount-drive": DriveScope(
                        selected_file_ids=["f2", "f1"],
                        display_metadata_by_file={
                            "f1": {"name": "1-blatant/requirements.txt"},
                            "f2": {"name": "2-partial/requirements.txt"},
                        },
                    )
                }
            ),
            github_scope_store=FakeStore(
                {"mount-github": GithubScope("Sora3780", "ip-risk-agent", "main")}
            ),
        )
    )
    return TestClient(app)


def test_drive_mount_lists_files_sorted_by_path() -> None:
    client = build_client()

    body = client.get(
        "/api/v1/source-connections/mounts/mount-drive/tracked-files"
    ).json()

    assert body["source_type"] == "GOOGLE_DRIVE"
    # Drive 화면과 같은 감각으로 읽히려면 폴더 구조 순이어야 한다.
    assert [f["path"] for f in body["files"]] == [
        "1-blatant/requirements.txt",
        "2-partial/requirements.txt",
    ]


def test_github_mount_describes_the_whole_repository() -> None:
    """GitHub 는 개별 파일이 아니라 저장소@브랜치 전체를 감시한다.

    빈 files 만 돌려주면 "아무것도 감시하지 않는다"로 읽힌다.
    """
    client = build_client()

    body = client.get(
        "/api/v1/source-connections/mounts/mount-github/tracked-files"
    ).json()

    assert body["descriptor"] == "Sora3780/ip-risk-agent@main 저장소 전체"
    assert body["files"] == []


def test_the_route_is_behind_mount_authz() -> None:
    calls: list = []
    client = build_client(authz_calls=calls)

    client.get("/api/v1/source-connections/mounts/mount-drive/tracked-files")

    assert calls == ["mount-drive"]
