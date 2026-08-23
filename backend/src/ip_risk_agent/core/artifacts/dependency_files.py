"""어떤 파일 이름이 의존성 선언인가.

## 왜 한 곳에 두는가

이 표는 두 곳이 각각 필요로 한다. **커넥터**는 파일을 가져오며 종류를 정해야 하고
(그 종류가 License 검사를 받을지 Patent 검사를 받을지를 가른다), **License
분석기**는 그 파일을 어떤 형식으로 읽을지 골라야 한다.

두 곳이 표를 따로 들고 있으면 어긋난다. 실제로 어긋나 있었다.

* Drive 는 ``requirements.txt`` 와 ``package.json`` 만 의존성으로 봤고, GitHub 과
  Local 은 거기에 ``pyproject.toml``·``setup.py``·``setup.cfg`` 를 더 봤다. 같은
  ``pyproject.toml`` 이 Drive 에서는 Patent 검사를, GitHub 에서는 License 검사를
  받았다.
* GitHub 과 Local 은 ``setup.py`` 를 의존성으로 분류했는데 **읽을 파서가 없었다.**
  그러면 License 분석기도 맡지 못하고 Patent 분석기도 종류가 맞지 않아 맡지
  못한다. 결과가 0 건이 되어 계약 위반으로 분석이 실패했다 — 거의 모든 파이썬
  저장소에 있는 파일이다.
* 분석기는 ``requirements`` 로 시작하는 이름을 모두 읽을 수 있는데 커넥터는
  ``requirements.txt`` 만 인정했다. ``requirements-dev.txt`` 는 읽을 수 있는데도
  Patent 쪽으로 갔다.

그래서 **읽을 수 있는 이름만** 여기에 적고, 두 곳이 모두 이 표를 본다.

## 경로는 거의 보지 않는다

파일 이름만으로 정한다. ``setup.cfg`` 는 저장소 어디에 있든 ``setup.cfg`` 다.

예외가 하나 있다. ``requirements/base.txt`` 처럼 **폴더로 나누는 관행**은 이름만 보면
알아볼 수 없어서, 부모 폴더가 ``requirements`` 인 경우만 함께 본다. 이 규칙은 알아보는
것을 **늘릴 뿐 줄이지 않는다.**
"""

from __future__ import annotations

from enum import StrEnum

from iprisk_contracts.common import ArtifactKind

#: 의존성 선언을 담은 종류. 커넥터가 이 종류로 분류한 것만 License 분석기가 맡는다.
#:
#: 여기 두는 이유는 이 표를 보는 곳이 셋이기 때문이다 — 커넥터가 종류를 정할 때,
#: 분석기가 맡을지 고를 때, 그리고 **조각내지 않고 통짜로 넘길지 정할 때**
#: (``connectors.common.segmentation``).
DEPENDENCY_KINDS = frozenset({ArtifactKind.MANIFEST, ArtifactKind.LOCKFILE})

#: ``requirements`` 로 시작하면 모두 같은 형식이다 — ``requirements-dev.txt``,
#: ``requirements.in`` 처럼 쓰는 관행이 넓다.
_REQUIREMENTS_PREFIX = "requirements"


class DependencyFormat(StrEnum):
    """읽을 수 있는 의존성 파일 형식. 파서가 있는 것만 있다."""

    REQUIREMENTS_TXT = "REQUIREMENTS_TXT"
    #: ``requirements.lock`` — 문법은 ``requirements.txt`` 와 같지만 **잠금 파일**이다.
    #: 형식을 나눠 두어야 파서가 낸 ``EXACT_PIN`` 을 ``LOCKFILE`` 로 올릴 수 있다.
    REQUIREMENTS_LOCK = "REQUIREMENTS_LOCK"
    PYPROJECT_TOML = "PYPROJECT_TOML"
    SETUP_CFG = "SETUP_CFG"
    PACKAGE_JSON = "PACKAGE_JSON"
    PACKAGE_LOCK_JSON = "PACKAGE_LOCK_JSON"
    UV_LOCK = "UV_LOCK"
    POETRY_LOCK = "POETRY_LOCK"

    @property
    def is_lockfile(self) -> bool:
        return self in {
            DependencyFormat.PACKAGE_LOCK_JSON,
            DependencyFormat.REQUIREMENTS_LOCK,
            DependencyFormat.UV_LOCK,
            DependencyFormat.POETRY_LOCK,
        }


#: 정확히 일치해야 하는 이름. **잠금 파일을 먼저 본다** — ``package-lock.json`` 은
#: ``package.json`` 을 포함하므로 순서가 뒤바뀌면 잘못된 파서를 고른다.
_EXACT_NAMES: tuple[tuple[str, DependencyFormat], ...] = (
    ("package-lock.json", DependencyFormat.PACKAGE_LOCK_JSON),
    ("uv.lock", DependencyFormat.UV_LOCK),
    ("poetry.lock", DependencyFormat.POETRY_LOCK),
    ("pyproject.toml", DependencyFormat.PYPROJECT_TOML),
    ("setup.cfg", DependencyFormat.SETUP_CFG),
    ("package.json", DependencyFormat.PACKAGE_JSON),
    #: pip 이 만든 제약 목록. 문법이 ``requirements.txt`` 와 같다.
    ("constraints.txt", DependencyFormat.REQUIREMENTS_TXT),
)


def file_name(logical_path: str) -> str:
    """경로에서 파일 이름만 뗀다. 구분자는 둘 다 받는다."""
    return logical_path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _in_requirements_directory(logical_path: str) -> bool:
    """``requirements/`` 안에 바로 놓인 파일인가.

    ``requirements/base.txt`` · ``requirements/dev.txt`` 처럼 폴더로 나누는 관행이 넓다.
    이름만 보면 ``base.txt`` 라 알아볼 수 없으므로 여기서만 **부모 폴더 하나**를 본다.

    아래 :func:`dependency_format` 의 "경로를 보지 않는다" 는 원칙은 그대로다 — 이
    규칙은 **알아보는 것을 늘릴 뿐 줄이지 않는다.** 어디에 있든 ``setup.cfg`` 는
    여전히 ``setup.cfg`` 다.
    """
    parts = logical_path.replace("\\", "/").strip("/").split("/")
    return len(parts) >= 2 and parts[-2].lower() == "requirements"


def dependency_format(logical_path: str) -> DependencyFormat | None:
    """이 파일을 어떤 형식으로 읽는가. 읽을 수 없으면 ``None``.

    ``setup.py`` 는 여기에 없다. 임의의 파이썬 코드라 실행하지 않고서는 의존성을
    확정할 수 없다. 읽지 못할 것을 의존성으로 분류하면 어느 분석기도 맡지 못해
    분석 자체가 실패한다. 저장소에서 ``setup.py`` 는 소스 코드로 다뤄진다.
    """
    name = file_name(logical_path)
    for candidate, item in _EXACT_NAMES:
        if name == candidate:
            return item
    if name.startswith(_REQUIREMENTS_PREFIX):
        # ``requirements.lock`` 은 같은 문법이지만 잠금 파일이다.
        if name.endswith(".lock"):
            return DependencyFormat.REQUIREMENTS_LOCK
        if name.endswith((".txt", ".in")):
            return DependencyFormat.REQUIREMENTS_TXT
    if _in_requirements_directory(logical_path) and name.endswith((".txt", ".in")):
        return DependencyFormat.REQUIREMENTS_TXT
    return None


__all__ = ["DEPENDENCY_KINDS", "DependencyFormat", "dependency_format", "file_name"]
