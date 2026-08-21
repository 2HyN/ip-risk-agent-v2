"""Mount 가 실제로 감시하는 파일 목록을 화면에 알려준다.

추적 스코프는 Integration 소유 저장소에 있고 Control 은 모른다. 그래서
"연결은 됐는데 무엇이 감시되는지 볼 수 없는" 상태였다 — 사용자는 폴더를
연결한 뒤 그 안의 어떤 파일이 인식됐는지 확인할 길이 없었다. 이 라우트가
그 목록을 읽기 전용으로 연다.

원문은 다루지 않는다. 파일의 **경로와 개수**뿐이다. 경로는 사용자가 직접
고른 폴더의 구조라 새로운 노출이 아니다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from iprisk_contracts.common import SourceType
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TrackedFile(BaseModel):
    id: str
    path: str


class TrackedFilesResponse(BaseModel):
    mount_id: str
    source_type: str
    # GitHub 는 개별 파일이 아니라 저장소@브랜치 전체를 감시한다. 그때는
    # files 대신 이 서술이 범위를 말한다.
    descriptor: str | None = None
    files: list[TrackedFile] = []


def create_tracked_files_router(
    *,
    mount_ref_resolver,
    authz_dependency,
    drive_scope_store=None,
    github_scope_store=None,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/v1/source-connections/mounts/{mount_id}/tracked-files",
        response_model=TrackedFilesResponse,
    )
    async def tracked_files(mount_id: str, request: Request) -> TrackedFilesResponse:
        await authz_dependency(request, mount_id)

        mount = await mount_ref_resolver(mount_id)
        source_type = getattr(mount, "source_type", None)

        if source_type is SourceType.GOOGLE_DRIVE and drive_scope_store is not None:
            scope = await drive_scope_store.load(mount_id)
            if scope is None:
                return TrackedFilesResponse(
                    mount_id=mount_id, source_type=source_type.value
                )
            metadata = scope.display_metadata_by_file or {}
            files = [
                TrackedFile(
                    id=file_id,
                    path=str((metadata.get(file_id) or {}).get("name") or file_id),
                )
                for file_id in scope.selected_file_ids
            ]
            # 폴더 구조 순으로 읽히는 것이 Drive 화면과 같은 감각이다.
            files.sort(key=lambda item: item.path)
            return TrackedFilesResponse(
                mount_id=mount_id, source_type=source_type.value, files=files
            )

        if source_type is SourceType.GITHUB and github_scope_store is not None:
            scope = await github_scope_store.load(mount_id)
            if scope is None:
                return TrackedFilesResponse(
                    mount_id=mount_id, source_type=source_type.value
                )
            return TrackedFilesResponse(
                mount_id=mount_id,
                source_type=source_type.value,
                descriptor=(
                    f"{scope.owner}/{scope.repo}@{scope.tracked_branch} 저장소 전체"
                ),
            )

        if source_type is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="unknown mount"
            )
        return TrackedFilesResponse(mount_id=mount_id, source_type=source_type.value)

    return router


__all__ = ["TrackedFile", "TrackedFilesResponse", "create_tracked_files_router"]
