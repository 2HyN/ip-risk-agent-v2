"""폴더 선택이 하위 파일 감시로 이어지는지 검증.

사용자는 폴더를 "폴더 안을 감시해 달라"는 뜻으로 고르지만, 변경 감지는
file id 정확 일치다. 펼치지 않으면 폴더 객체 하나만 추적되어 안의 문서가
전부 빠진다 — 기대와 실제가 조용히 어긋나는 지점이라 여기서 잠근다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from iprisk_contracts.common import SourceType

from ip_risk_agent.composition.drive_selection import (
    MAX_FILES,
    DriveSelectionExpander,
)
from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.common.errors import NotFoundError

FOLDER = "application/vnd.google-apps.folder"


@dataclass
class File:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None = None
    revision_id: str | None = None
    web_view_link: str | None = None


class FakeProvider:
    """items: id -> File, tree: folder id -> 자식 id 목록."""

    def __init__(self, items: dict[str, File], tree: dict[str, list[str]]) -> None:
        self._items = items
        self._tree = tree

    def get_file(self, file_id: str) -> File:
        if file_id not in self._items:
            raise NotFoundError(provider="google_drive", safe_message="missing")
        return self._items[file_id]

    def list_children(self, folder_id: str) -> list[File]:
        return [self._items[i] for i in self._tree.get(folder_id, [])]

    def export_token(self) -> dict:
        return {"access_token": "refreshed"}


CREDENTIAL = CredentialRef(
    provider=SourceType.GOOGLE_DRIVE,
    connection_id="conn-1",
    secret_name="drive-oauth-token",
    key_id="key-1",
)


class FakeCredentialLookup:
    async def resolve_credential_ref(self, connection_id: str) -> CredentialRef:
        return CREDENTIAL


class FakeVault:
    def __init__(self) -> None:
        self.updates: list[str] = []

    async def get(self, ref) -> str:
        return '{"access_token": "original"}'

    async def update(self, ref, secret: str) -> None:
        self.updates.append(secret)


def expander(items: dict[str, File], tree: dict[str, list[str]]) -> DriveSelectionExpander:
    provider = FakeProvider(items, tree)
    return DriveSelectionExpander(
        credential_lookup=FakeCredentialLookup(),
        credential_vault=FakeVault(),
        provider_factory=type(
            "F", (), {"create": staticmethod(lambda token: provider)}
        )(),
    )


@pytest.mark.asyncio
async def test_a_folder_expands_to_every_file_inside_recursively() -> None:
    items = {
        "root": File("root", "기획서모음", FOLDER),
        "sub": File("sub", "v1", FOLDER),
        "doc-1": File("doc-1", "페르소나.docx", "application/msword"),
        "doc-2": File("doc-2", "요구사항.md", "text/markdown"),
        "doc-3": File("doc-3", "회의록.txt", "text/plain"),
    }
    tree = {"root": ["doc-1", "sub"], "sub": ["doc-2", "doc-3"]}

    files = await expander(items, tree).expand("conn-1", ["root"])

    assert {f.file_id for f in files} == {"doc-1", "doc-2", "doc-3"}
    # 폴더 자체는 감시 목록에 남지 않는다. 내용이 없어 분석할 수 없다.
    assert all(f.mime_type != FOLDER for f in files)


@pytest.mark.asyncio
async def test_plain_files_pass_through_unchanged() -> None:
    items = {"doc-1": File("doc-1", "기획서.docx", "application/msword")}

    files = await expander(items, {}).expand("conn-1", ["doc-1"])

    assert [f.file_id for f in files] == ["doc-1"]


@pytest.mark.asyncio
async def test_duplicate_paths_yield_one_entry() -> None:
    """폴더와 그 안의 파일을 둘 다 고르면 파일은 한 번만 나와야 한다."""
    items = {
        "root": File("root", "폴더", FOLDER),
        "doc-1": File("doc-1", "기획서.docx", "application/msword"),
    }
    tree = {"root": ["doc-1"]}

    files = await expander(items, tree).expand("conn-1", ["root", "doc-1"])

    assert [f.file_id for f in files] == ["doc-1"]


@pytest.mark.asyncio
async def test_expansion_is_capped_not_unbounded() -> None:
    """계정 루트급 폴더를 골라도 폭주하지 않는다. 잘림은 로그로 남는다."""
    items = {"root": File("root", "큰폴더", FOLDER)}
    children = []
    for i in range(MAX_FILES + 50):
        fid = f"doc-{i:04d}"
        items[fid] = File(fid, f"파일{i}.md", "text/markdown")
        children.append(fid)
    tree = {"root": children}

    files = await expander(items, tree).expand("conn-1", ["root"])

    assert len(files) == MAX_FILES


@pytest.mark.asyncio
async def test_a_broken_item_does_not_block_the_rest() -> None:
    items = {
        "root": File("root", "폴더", FOLDER),
        "doc-2": File("doc-2", "살아있는 문서.md", "text/markdown"),
    }
    # doc-gone 은 items 에 없다 — 목록에는 있는데 조회가 실패하는 상황.
    tree = {"root": ["doc-2"]}

    files = await expander(items, tree).expand("conn-1", ["doc-gone", "root"])

    assert [f.file_id for f in files] == ["doc-2"]


@pytest.mark.asyncio
async def test_expansion_order_is_deterministic() -> None:
    """Mount 식별 키가 선택 목록에서 나온다. 순서가 흔들리면 재시도마다
    다른 Mount 가 생긴다."""
    items = {
        "root": File("root", "폴더", FOLDER),
        "b": File("b", "나중.md", "text/markdown"),
        "a": File("a", "먼저.md", "text/markdown"),
    }
    tree = {"root": ["b", "a"]}

    first = await expander(items, tree).expand("conn-1", ["root"])
    second = await expander(items, tree).expand("conn-1", ["root"])

    assert [f.file_id for f in first] == [f.file_id for f in second]
