"""통합 시험 픽스처가 시나리오가 말하는 대로 읽히는가.

``docs/INTEGRATION_TEST_SCENARIO.md`` 는 픽스처 저장소의 파일마다 "무엇을 붙잡는가" 를
적어 두고, 그 표를 근거로 운영에서 본 결과를 합격·불합격으로 가른다. 픽스처가 조용히
어긋나면 **시나리오가 아무것도 확인하지 않으면서 통과한다.**

여기서는 외부를 부르지 않는다. 파일 이름이 인식되는지와 파서가 무엇을 내는지만 본다 —
등급은 레지스트리가 정하므로 실물 시험(``-m live``)의 몫이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ip_risk_agent.core.artifacts.dependency_files import (
    DependencyFormat,
    dependency_format,
)
from ip_risk_agent.intelligence.license import lockfiles, manifests
from ip_risk_agent.intelligence.license.dependency_models import (
    DependencyParseError,
    ResolutionKind,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "integration-repo"

#: 분석기가 쓰는 것과 같은 표. ``requirements.lock`` 만 신뢰도를 올려 부른다.
_PARSERS = {
    DependencyFormat.REQUIREMENTS_TXT: manifests.parse_requirements_txt,
    DependencyFormat.REQUIREMENTS_LOCK: lambda text, path: (
        manifests.parse_requirements_txt(text, path, lockfile=True)
    ),
    DependencyFormat.PYPROJECT_TOML: manifests.parse_pyproject_toml,
    DependencyFormat.SETUP_CFG: manifests.parse_setup_cfg,
    DependencyFormat.PACKAGE_JSON: manifests.parse_package_json,
    DependencyFormat.PACKAGE_LOCK_JSON: lockfiles.parse_package_lock_json,
    DependencyFormat.UV_LOCK: lockfiles.parse_uv_lock,
    DependencyFormat.POETRY_LOCK: lockfiles.parse_poetry_lock,
}

#: 파일 -> (형식, 선언 이름들). 시나리오 §1 의 표와 같아야 한다.
EXPECTED: dict[str, tuple[DependencyFormat, tuple[str, ...]]] = {
    "package.json": (
        DependencyFormat.PACKAGE_JSON,
        ("chalk", "node-forge", "left-pad"),
    ),
    "package-lock.json": (
        DependencyFormat.PACKAGE_LOCK_JSON,
        ("chalk", "node-forge"),
    ),
    "requirements.txt": (DependencyFormat.REQUIREMENTS_TXT, ("requests", "pyqt5")),
    "requirements-dev.txt": (DependencyFormat.REQUIREMENTS_TXT, ("pikepdf",)),
    "requirements/base.txt": (
        DependencyFormat.REQUIREMENTS_TXT,
        ("matplotlib", "pandas"),
    ),
    "constraints.txt": (DependencyFormat.REQUIREMENTS_TXT, ("weasyprint",)),
    "requirements.lock": (DependencyFormat.REQUIREMENTS_LOCK, ("paramiko",)),
    "pyproject.toml": (DependencyFormat.PYPROJECT_TOML, ("mysqlclient",)),
    "setup.cfg": (DependencyFormat.SETUP_CFG, ("pymupdf",)),
    "uv.lock": (DependencyFormat.UV_LOCK, ("nvidia-cudnn-cu12",)),
    "poetry.lock": (DependencyFormat.POETRY_LOCK, ("pyarmor",)),
    "missing-version/package.json": (DependencyFormat.PACKAGE_JSON, ("chalk",)),
}

#: 일부러 못 읽게 둔 것. 0-C 가 이것을 `PARTIAL` 로 만든다.
UNREADABLE = "broken/package.json"


def _files() -> list[str]:
    return sorted(
        path.relative_to(FIXTURE).as_posix()
        for path in FIXTURE.rglob("*")
        if path.is_file()
    )


def test_the_fixture_holds_exactly_what_the_scenario_lists() -> None:
    """파일이 늘거나 줄면 시나리오의 표가 거짓이 된다."""
    assert set(_files()) == set(EXPECTED) | {UNREADABLE}


def test_nothing_in_the_fixture_goes_down_the_patent_path() -> None:
    """KIPRIS 는 월 1,000 회다.

    소스 코드나 문서가 하나라도 섞이면 특허 분석이 돌고 한 건이 11 회쯤 쓴다.
    시나리오가 "KIPRIS 0 회" 라고 약속하므로 그것을 여기서 지킨다.
    """
    unrecognized = [name for name in _files() if dependency_format(name) is None]
    assert unrecognized == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_fixture_file_parses_to_what_the_scenario_says(name: str) -> None:
    fmt, expected_names = EXPECTED[name]
    assert dependency_format(name) is fmt
    found = _PARSERS[fmt]((FIXTURE / name).read_text(encoding="utf-8"), name)
    assert tuple(item.name for item in found) == expected_names


def test_the_unreadable_file_raises_instead_of_returning_nothing() -> None:
    """0-C 의 전부다.

    예전에는 파싱 실패를 삼키고 ``[]`` 를 돌려줬고, 그러면 "온전히 읽었고 아무것도
    선언하지 않았다" 와 구별되지 않아 **멀쩡한 위험이 해소**됐다.
    """
    assert dependency_format(UNREADABLE) is DependencyFormat.PACKAGE_JSON
    with pytest.raises(DependencyParseError):
        manifests.parse_package_json(
            (FIXTURE / UNREADABLE).read_text(encoding="utf-8"), UNREADABLE
        )


def test_the_lock_files_carry_lockfile_confidence() -> None:
    """0-J 의 절반이다. ``requirements.lock`` 은 문법이 같고 신뢰도만 다르다."""
    for name in ("package-lock.json", "uv.lock", "poetry.lock", "requirements.lock"):
        fmt, _ = EXPECTED[name]
        found = _PARSERS[fmt]((FIXTURE / name).read_text(encoding="utf-8"), name)
        assert found, name
        assert all(item.resolution is ResolutionKind.LOCKFILE for item in found), name


def test_the_declaration_count_matches_the_scenario() -> None:
    """시나리오 §1 이 "선언 17 건" 이라고 약속한다."""
    total = sum(
        len(_PARSERS[fmt]((FIXTURE / name).read_text(encoding="utf-8"), name))
        for name, (fmt, _) in EXPECTED.items()
    )
    assert total == 17
