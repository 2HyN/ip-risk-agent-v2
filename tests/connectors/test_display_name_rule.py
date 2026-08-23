"""보이는 이름은 소스와 경로에 상관없이 같은 규칙으로 붙는다 (§6.3 · 1-G).

이름을 붙이는 곳이 다섯이었고 서로 달랐다. 실패하지는 않았다 — 등록이 갱신하고
``display_name`` 은 불변 조건이 아니다. 그래서 **하위 폴더 파일의 이름이 첫 push 뒤에
조용히 바뀌었다.** 목록에서 ``main.py`` 였던 것이 ``src/app/main.py`` 가 된다.

조용한 종류의 어긋남이라 시험으로 붙잡아 둔다.
"""

from __future__ import annotations

import pytest

from ip_risk_agent.core.artifacts.naming import display_name_for


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("main.py", "main.py"),
        ("src/app/main.py", "main.py"),
        ("docs/design.md", "design.md"),
        # Local 은 기기가 보낸 상대 경로를 그대로 넘긴다. 윈도우 기기는 역슬래시다.
        (r"src\app\main.py", "main.py"),
        (r"src/app\main.py", "main.py"),
        # Drive 에는 경로가 없다. 이름이 그대로 통과해야 한다.
        ("설계 메모", "설계 메모"),
    ),
)
def test_a_folder_never_reaches_the_visible_name(path: str, expected: str) -> None:
    """트리는 ``logical_path`` 가 만든다. 이름까지 경로를 들면 폴더가 두 번 나온다."""
    assert display_name_for(path) == expected


def test_a_name_is_never_invented() -> None:
    """빈 값을 그럴듯한 것으로 바꾸면 부르는 쪽의 검증이 영영 통과한다."""
    assert display_name_for("") == ""


def test_the_mount_and_the_push_path_agree() -> None:
    """GitHub 은 마운트에서 마지막 조각을, push 에서 **전체 경로**를 넣었다.

    그래서 같은 파일이 첫 push 를 받는 순간 이름이 바뀌었다.
    """
    path = "backend/src/app/main.py"
    assert display_name_for(path) == display_name_for(path.rsplit("/", 1)[-1])


def test_every_connector_uses_the_one_rule() -> None:
    """규칙을 옮겨 적으면 다시 갈라진다. 다섯 곳이 모두 여기서 가져온다."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "backend" / "src" / "ip_risk_agent"
    offenders: list[str] = []
    for path in sorted((root / "connectors").rglob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith("display_name"):
                continue
            if "display_name_for(" in stripped:
                continue
            # 이미 만들어진 참조를 그대로 옮기는 것은 이름을 붙이는 것이 아니다.
            if "change.artifact.display_name" in stripped:
                continue
            if "self._display_name(" in stripped:
                continue
            offenders.append(f"{path.name}:{number} {stripped}")
    assert offenders == []
