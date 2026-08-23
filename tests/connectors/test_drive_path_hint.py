"""Drive 아티팩트가 부모 경로를 갖는다 (§6.1 · 1-E).

예전에는 ``logical_path_hint`` 가 ``None`` 이라 Drive 아티팩트의 ``logical_path`` 가
``별칭/파일이름`` 으로 **평평했다.** 폴더가 다른 같은 이름의 파일이 목록에서 구별되지
않고, UI 트리를 만들 근거가 없었다. GitHub 과 Local 은 경로를 그대로 들고 오므로 Drive
만 부모를 물어야 안다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ip_risk_agent.connectors.google_drive.paths import (
    MAX_PATH_DEPTH,
    TRUNCATED_MARKER,
    resolve_path_hint,
    sanitize_segment,
)


@dataclass(frozen=True)
class _Entry:
    name: str
    parents: tuple[str, ...]


class _Provider:
    def __init__(self, entries: dict[str, _Entry]) -> None:
        self._entries = entries
        self.calls = 0

    def get_file(self, file_id: str) -> _Entry:
        self.calls += 1
        try:
            return self._entries[file_id]
        except KeyError as exc:  # 공유 범위 밖의 조상
            raise PermissionError(file_id) from exc


def test_the_parent_chain_becomes_the_path() -> None:
    provider = _Provider(
        {"docs": _Entry("docs", ("project",)), "project": _Entry("project", ())}
    )
    assert (
        resolve_path_hint(provider, "f", "design.md", ("docs",))
        == "project/docs/design.md"
    )


def test_a_file_at_the_root_is_just_its_name() -> None:
    assert resolve_path_hint(_Provider({}), "f", "design.md", ()) == "design.md"


def test_an_ancestor_we_cannot_read_ends_the_path() -> None:
    """공유 범위 밖은 오류가 아니다. **우리가 볼 수 있는 만큼**이 경로다."""
    provider = _Provider({"docs": _Entry("docs", ("hidden",))})
    assert resolve_path_hint(provider, "f", "a.md", ("docs",)) == "docs/a.md"


def test_a_truncated_path_says_so() -> None:
    """조용히 자르면 그 경로가 뿌리부터인 것처럼 읽힌다 (§6.1)."""
    deep = {f"d{index}": _Entry(f"lvl{index}", (f"d{index + 1}",)) for index in range(40)}
    found = resolve_path_hint(_Provider(deep), "f", "leaf.md", ("d0",))
    assert found.startswith(TRUNCATED_MARKER + "/")
    assert found.count("/") == MAX_PATH_DEPTH + 1


def test_ancestors_are_looked_up_once_per_sweep() -> None:
    """같은 폴더가 여러 파일의 조상이다. 매번 물으면 호출이 파일 수만큼 곱해진다."""
    provider = _Provider(
        {"docs": _Entry("docs", ("project",)), "project": _Entry("project", ())}
    )
    cache: dict[str, tuple[str, tuple[str, ...]]] = {}
    for name in ("a.md", "b.md", "c.md"):
        resolve_path_hint(provider, "f", name, ("docs",), cache=cache)
    assert provider.calls == 2, "폴더 둘을 한 번씩만 묻는다"


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("a/b.md", "a_b.md"),
        (r"a\b.md", "a_b.md"),
        ("  spaced  ", "spaced"),
        ("..", "_"),
        ("", "_"),
    ),
)
def test_a_name_cannot_change_the_shape_of_the_path(name: str, expected: str) -> None:
    """Drive 이름에는 ``/`` 가 들어갈 수 있다.

    그대로 이으면 조각 하나가 둘이 되어 경로의 뜻이 바뀐다. 경로는 제외 패턴 판정에
    쓰이므로 (§9.1) 이름이 경로의 모양을 바꾸게 두면 안 된다.
    """
    assert sanitize_segment(name) == expected
