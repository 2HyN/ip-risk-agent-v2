"""Picker 선택을 실제 감시 목록으로 펼친다.

사용자는 "이 폴더를 감시해 줘"라고 생각하며 폴더를 고른다. 그런데 변경
감지는 file id 정확 일치로 동작하므로, 폴더 id 하나만 추적하면 **폴더
객체의 이름 변경** 같은 것만 잡히고 안의 문서들은 전부 빠진다. 사용자가
기대한 것과 시스템이 하는 일이 갈라지는 지점이라, Mount 를 만들기 전에
폴더를 하위 파일들로 펼쳐 그 간극을 없앤다.

한계도 여기서 정해진다 — 펼침은 **Mount 생성 시점의 스냅샷**이다. 이후
폴더에 새로 추가되는 파일은 자동으로 추적되지 않는다. 그것까지 하려면
변경 감지가 부모 관계를 되짚어야 하는데, 지금의 감지 계약(file id 일치)
을 바꾸는 일이라 별도 작업이다. 이 한계는 화면 문구에도 그대로 적는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ip_risk_agent.connectors.common.errors import SourceConnectorError

logger = logging.getLogger(__name__)

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True, slots=True)
class ExpandedFile:
    """확장 결과 하나. 파일 메타데이터에 **폴더 상대 경로**를 붙인다.

    파일 이름만 남기면 페르소나 폴더마다 있는 requirements.txt 가 화면에서
    전부 같은 이름으로 보여, 어느 폴더의 위반인지 알 수 없게 된다. 경로는
    걷는 동안만 알 수 있으므로 여기서 붙여서 내보낸다.
    """

    file: object
    path: str

    @property
    def file_id(self) -> str:
        return self.file.file_id

# 폭주 방지. 사용자가 계정 루트급 폴더를 고르면 수천 파일이 쏟아질 수 있다.
# 잘라낸 사실은 반드시 로그로 남긴다 — 조용히 자르면 "전부 검사했다"로 읽힌다.
MAX_FILES = 300
MAX_DEPTH = 10


class DriveSelectionExpander:
    """선택된 id 목록에서 폴더를 하위 파일로 재귀 확장한다."""

    def __init__(self, *, credential_lookup, credential_vault, provider_factory) -> None:
        self._credential_lookup = credential_lookup
        self._credential_vault = credential_vault
        self._provider_factory = provider_factory

    async def expand(self, connection_id: str, selected_file_ids: list[str]) -> list:
        """파일(폴더 아님)의 DriveFile 목록을 돌려준다. 순서는 결정적이다."""
        import json  # noqa: PLC0415 - 표준 라이브러리 지연 import

        credential_ref = await self._credential_lookup.resolve_credential_ref(
            connection_id
        )
        raw_token = await self._credential_vault.get(credential_ref)
        provider = self._provider_factory.create(json.loads(raw_token))

        files: dict[str, ExpandedFile] = {}
        truncated = False

        def keep(file, path: str) -> None:
            # 폴더와 개별 파일을 함께 골랐을 때는 경로가 있는 쪽(폴더 내부)이
            # 더 많은 정보를 담는다.
            existing = files.get(file.file_id)
            if existing is None or ("/" in path and "/" not in existing.path):
                files[file.file_id] = ExpandedFile(file=file, path=path)

        def walk(file_id: str, depth: int, prefix: str) -> None:
            nonlocal truncated
            if len(files) >= MAX_FILES:
                truncated = True
                return
            try:
                file = provider.get_file(file_id)
            except SourceConnectorError:
                # 이 항목만 건너뛴다. 하나가 막혔다고 폴더 전체가 빠지면
                # 사용자가 이유를 알 수 없다.
                logger.warning("selection expand: lookup failed for one item")
                return
            if file.mime_type != FOLDER_MIME_TYPE:
                keep(file, f"{prefix}{file.name}" if prefix else file.name)
                return
            if depth >= MAX_DEPTH:
                truncated = True
                return
            try:
                children = provider.list_children(file_id)
            except SourceConnectorError:
                logger.warning("selection expand: folder listing failed")
                return
            # 직접 고른 폴더 이름은 경로에 넣지 않는다. Mount alias 가 이미
            # 그 맥락을 담고, 하위 폴더부터가 파일을 구분해 주는 정보다.
            child_prefix = prefix if depth == 0 else f"{prefix}{file.name}/"
            # 이름순으로 걷는다. 같은 폴더면 같은 목록·같은 순서가 나와야
            # Mount 식별 키가 재시도에도 안정적이다.
            for child in sorted(children, key=lambda item: (item.name, item.file_id)):
                if len(files) >= MAX_FILES:
                    truncated = True
                    return
                if child.mime_type == FOLDER_MIME_TYPE:
                    walk(child.file_id, depth + 1, child_prefix)
                else:
                    keep(child, f"{child_prefix}{child.name}")

        for file_id in selected_file_ids:
            walk(file_id, 0, "")

        if truncated:
            logger.warning(
                "selection expand: capped at %d files (connection=%s) — "
                "일부 파일이 감시 대상에서 빠졌다",
                MAX_FILES,
                connection_id,
            )

        await self._credential_vault.update(
            credential_ref, json.dumps(provider.export_token())
        )
        return list(files.values())


__all__ = [
    "DriveSelectionExpander",
    "ExpandedFile",
    "FOLDER_MIME_TYPE",
    "MAX_DEPTH",
    "MAX_FILES",
]
