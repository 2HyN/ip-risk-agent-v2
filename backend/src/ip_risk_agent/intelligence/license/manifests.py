"""매니페스트 파서.

입력은 파일이 아니라 Security Gate 를 통과한 텍스트다. 이 plane 은 Source Provider 를
직접 읽지 않는다 (Master Spec 59-7).

파서는 관대해야 한다. 한 줄이 깨졌다고 파일 전체를 버리면 나머지 의존성까지 놓친다.
"""

from __future__ import annotations

from configparser import ConfigParser

import json
import re
import tomllib

from .dependency_models import (
    DependencyParseError,
    DependencyDeclaration,
    Ecosystem,
    ResolutionKind,
    normalize_package_name,
)

# 이름[extras] 뒤에 오는 버전 지정자. 환경 표지(; python_version…)는 잘라 낸다.
_REQUIREMENT = re.compile(
    r"""^\s*
    (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)
    (?:\[[^\]]*\])?
    \s*(?P<spec>[^;#]*)
    """,
    re.VERBOSE,
)
_EXACT = re.compile(r"^==\s*(?P<version>[A-Za-z0-9][^\s,;]*)$")

# requirements.txt 에서 의존성이 아닌 줄.
_DIRECTIVE_PREFIXES = ("-", "--", "http://", "https://", "git+", ".", "/")


def _classify_spec(spec: str) -> tuple[str | None, ResolutionKind]:
    """버전 지정자에서 확정 버전을 뽑는다. ``==`` 만 확정으로 본다."""
    cleaned = spec.strip().rstrip(",").strip()
    if not cleaned:
        return None, ResolutionKind.UNRESOLVED
    if match := _EXACT.match(cleaned):
        return match.group("version"), ResolutionKind.EXACT_PIN
    return None, ResolutionKind.RANGE


def parse_requirements_txt(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """pip requirements 형식."""
    found: list[DependencyDeclaration] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(_DIRECTIVE_PREFIXES):
            continue
        match = _REQUIREMENT.match(line)
        if not match:
            continue
        version, resolution = _classify_spec(match.group("spec"))
        found.append(
            DependencyDeclaration(
                ecosystem=Ecosystem.PYPI,
                name=normalize_package_name(Ecosystem.PYPI, match.group("name")),
                version=version,
                resolution=resolution,
                raw_spec=line,
                source_path=source_path,
            )
        )
    return found


def parse_setup_cfg(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """setuptools ``setup.cfg`` 의 ``install_requires`` 와 extras.

    같은 배포판의 ``setup.py`` 는 읽지 않는다 — 임의의 파이썬 코드라 실행하지
    않고서는 의존성을 확정할 수 없다. ``setup.cfg`` 는 선언이라 읽을 수 있고,
    그래서 이쪽만 License 검사 대상이다.

    각 줄의 문법은 requirements 와 같으므로 그 판독을 그대로 쓴다.
    """
    parser = ConfigParser()
    try:
        parser.read_string(text)
    except Exception as exc:  # noqa: BLE001 - 어떤 형식 오류든 "못 읽었다" 다
        raise DependencyParseError("setup.cfg is not readable") from exc

    lines: list[str] = []
    if parser.has_option("options", "install_requires"):
        lines.extend(parser.get("options", "install_requires").splitlines())
    if parser.has_section("options.extras_require"):
        for _name, value in parser.items("options.extras_require"):
            lines.extend(value.splitlines())

    found: list[DependencyDeclaration] = []
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = _REQUIREMENT.match(line)
        if not match:
            continue
        version, resolution = _classify_spec(match.group("spec"))
        found.append(
            DependencyDeclaration(
                ecosystem=Ecosystem.PYPI,
                name=normalize_package_name(Ecosystem.PYPI, match.group("name")),
                version=version,
                resolution=resolution,
                raw_spec=line,
                source_path=source_path,
            )
        )
    return found


def parse_pyproject_toml(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """PEP 621 ``project.dependencies`` 와 optional-dependencies.

    poetry 의 ``tool.poetry.dependencies`` 는 문법이 달라 별도로 다룬다.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DependencyParseError("pyproject.toml is not readable") from exc

    specs: list[str] = []
    project = document.get("project") or {}
    if isinstance(project.get("dependencies"), list):
        specs.extend(str(item) for item in project["dependencies"])
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                specs.extend(str(item) for item in group)

    found = [
        declaration
        for spec in specs
        for declaration in parse_requirements_txt(spec, source_path)
    ]

    poetry = ((document.get("tool") or {}).get("poetry") or {}).get("dependencies")
    if isinstance(poetry, dict):
        for name, constraint in poetry.items():
            if name.lower() == "python":
                continue
            # {version = "^1.0", optional = true} 형태도 온다.
            raw = constraint.get("version") if isinstance(constraint, dict) else constraint
            version, resolution = (
                (str(raw), ResolutionKind.EXACT_PIN)
                if isinstance(raw, str) and re.fullmatch(r"\d[\w.+-]*", raw)
                else (None, ResolutionKind.RANGE if raw else ResolutionKind.UNRESOLVED)
            )
            found.append(
                DependencyDeclaration(
                    ecosystem=Ecosystem.PYPI,
                    name=normalize_package_name(Ecosystem.PYPI, name),
                    version=version,
                    resolution=resolution,
                    raw_spec=f"{name} = {raw!r}",
                    source_path=source_path,
                )
            )
    return found


# npm 범위 문법에서 확정 버전으로 볼 수 있는 형태 (1.2.3, 1.2.3-beta.1).
_NPM_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

_NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def parse_package_json(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """npm 매니페스트."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DependencyParseError("package.json is not readable") from exc
    if not isinstance(document, dict):
        raise DependencyParseError("package.json is not an object")

    found: list[DependencyDeclaration] = []
    for section in _NPM_SECTIONS:
        entries = document.get(section)
        if not isinstance(entries, dict):
            continue
        for name, raw in entries.items():
            spec = str(raw)
            if _NPM_EXACT.fullmatch(spec):
                version, resolution = spec, ResolutionKind.EXACT_PIN
            else:
                version, resolution = None, ResolutionKind.RANGE
            found.append(
                DependencyDeclaration(
                    ecosystem=Ecosystem.NPM,
                    name=normalize_package_name(Ecosystem.NPM, name),
                    version=version,
                    resolution=resolution,
                    raw_spec=f"{name}@{spec}",
                    source_path=source_path,
                )
            )
    return found
