"""공유받은 폴더를 추적 범위로 다룬다 (§6.1 · 1-F).

## 무엇이 바뀌는가

예전 `DriveTrackingScope` 는 **file id 의 명단**이었다. "추적 대상인가" 가 "이 id 가
명단에 있는가" 였고, 그래서 **마운트한 뒤에 폴더에 넣은 파일이 영영 잡히지 않았다.**
변경 피드에는 오는데(1-A 실측) 명단에 없다고 버려졌다.

v1 이 정확히 그렇게 실패했다 — 폴더 펼침이 **연결 시점의 스냅샷**이었다. 그리고 이
서비스의 운영 방식이 "추적할 파일을 지정 폴더에 넣어 두는 것" 이므로, 넣어도 안 잡히는
것은 기능이 없는 것과 같다.

그래서 판정을 **정적인 명단**에서 **동적인 소속**으로 바꾼다. 넣으면 잡히고 빼면
빠진다. GitHub 이 저장소를, Local 이 폴더를 다루는 것과 같은 모양이 된다.

## 바로가기를 따라가지 않는다

공유받은 폴더 안에 바로가기를 하나 두면 그 대상은 **폴더 밖에 있어도** 읽히게 된다.
따라가는 순간 "공유한 폴더만 본다" 가 깨진다. 지금까지는 통과 목록에 없어서 막혔는데
그것은 규칙이 아니라 우연이었다 (§6.1).

## 상한

v1 의 값을 그대로 쓴다 — **항목 300 · 깊이 10**. 골라 담는 폴더에는 넉넉하다.

**자른 것을 조용히 넘기지 않는다.** 잘렸다는 사실을 함께 돌려주고 부르는 쪽이 남긴다.
조용히 자르면 "전부 검사했다" 로 읽힌다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import FOLDER_MIME_TYPE, SHORTCUT_MIME_TYPE, DriveFile

#: v1 이 쓴 값. §6.1 이 새로 정할 이유가 없으면 그대로 쓰기로 했다.
MAX_FOLDER_ITEMS = 300
MAX_FOLDER_DEPTH = 10


class _FolderReader(Protocol):
    def get_file(self, file_id: str) -> DriveFile: ...
    def list_folder_children(self, folder_id: str, page_token: str | None = None): ...


@dataclass(frozen=True, slots=True)
class FolderListing:
    files: tuple[DriveFile, ...]
    #: 상한에 걸려 멈췄는가. 부르는 쪽이 이것을 남겨야 한다.
    truncated: bool = False


def is_followable(file: DriveFile) -> bool:
    """이 항목을 추적 대상으로 볼 것인가.

    폴더는 내려갈 대상이지 아티팩트가 아니고, 바로가기는 **따라가지 않는다.**
    """
    return file.mime_type not in {FOLDER_MIME_TYPE, SHORTCUT_MIME_TYPE}


def list_folder_files(
    provider: _FolderReader,
    folder_id: str,
    *,
    max_items: int = MAX_FOLDER_ITEMS,
    max_depth: int = MAX_FOLDER_DEPTH,
) -> FolderListing:
    """폴더 아래의 파일을 전부. 하위 폴더까지 내려간다."""
    found: list[DriveFile] = []
    seen: set[str] = {folder_id}
    truncated = False
    frontier: list[tuple[str, int]] = [(folder_id, 0)]

    while frontier:
        current, depth = frontier.pop(0)
        page_token = None
        while True:
            page = provider.list_folder_children(current, page_token)
            for item in page.files:
                if item.file_id in seen:
                    # Drive 는 한 항목이 여러 부모를 가질 수 있다. 두 번 담지 않는다.
                    continue
                seen.add(item.file_id)
                if item.mime_type == FOLDER_MIME_TYPE:
                    if depth + 1 <= max_depth:
                        frontier.append((item.file_id, depth + 1))
                    else:
                        truncated = True
                    continue
                if not is_followable(item):
                    continue
                if len(found) >= max_items:
                    truncated = True
                    return FolderListing(tuple(found), truncated=True)
                found.append(item)
            page_token = page.next_page_token
            if page_token is None:
                break

    return FolderListing(tuple(found), truncated=truncated)


def is_inside_folder(
    provider: _FolderReader,
    file_id: str,
    folder_id: str,
    *,
    cache: dict[str, tuple[str, ...]] | None = None,
    max_depth: int = MAX_FOLDER_DEPTH,
) -> bool:
    """이 파일이 그 폴더 아래에 있는가.

    부모를 따라 올라간다. 명단을 보는 것이 아니라 **지금 어디에 있는지**를 묻는다 —
    그래서 넣으면 잡히고 빼면 빠진다.

    읽지 못하는 조상에서 멈춘다. 공유 범위 밖이면 우리 폴더 아래가 아니다.
    """
    memo = cache if cache is not None else {}
    try:
        found = provider.get_file(file_id)
    except Exception:  # noqa: BLE001 - 읽지 못하면 우리 것이 아니다
        return False
    if not is_followable(found):
        return False

    frontier = list(found.parents)
    depth = 0
    while frontier and depth < max_depth:
        parent = frontier.pop(0)
        if parent == folder_id:
            return True
        parents = memo.get(parent)
        if parents is None:
            try:
                parents = tuple(provider.get_file(parent).parents)
            except Exception:  # noqa: BLE001
                parents = ()
            memo[parent] = parents
        frontier.extend(parents)
        depth += 1
    return False


__all__ = [
    "MAX_FOLDER_DEPTH",
    "MAX_FOLDER_ITEMS",
    "FolderListing",
    "is_followable",
    "is_inside_folder",
    "list_folder_files",
]
