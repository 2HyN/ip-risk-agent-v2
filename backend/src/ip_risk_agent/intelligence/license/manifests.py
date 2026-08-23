"""매니페스트 파서.

입력은 파일이 아니라 Security Gate 를 통과한 텍스트다. 이 plane 은 Source Provider 를
직접 읽지 않는다 (Master Spec 59-7).

파서는 관대해야 한다. 한 줄이 깨졌다고 파일 전체를 버리면 나머지 의존성까지 놓친다.
**다만 관대한 것과 조용한 것은 다르다.** 읽지 못한 줄은 남기고 호출부가 coverage 를
낮춘다 — 그러지 않으면 "온전히 읽었고 아무것도 없었다" 가 되어 멀쩡한 Risk 가 해소된다.
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


def _strip_byte_order_mark(text: str) -> str:
    """맨 앞의 BOM 을 뗀다.

    BOM 은 파일의 인코딩 표시이지 내용이 아니다. 떼지 않으면 첫 줄이
    ``﻿requests==2.31.0`` 이 되어 이름 패턴에 걸리지 않고, 그 줄이 **조용히**
    사라진다.

    윈도우에서는 흔하다. 메모장도, PowerShell 의 ``Set-Content -Encoding utf8`` 도
    BOM 을 붙인다. 실제로 이것 때문에 지우지도 않은 의존성의 Risk 가 해소됐다.
    """
    return text.lstrip("﻿")


def _scan_requirements(
    text: str, source_path: str | None, *, lockfile: bool
) -> tuple[list[DependencyDeclaration], list[str]]:
    """``(읽은 선언, 읽지 못한 줄)``.

    두 가지를 **한 곳에서** 만든다. 따로 두면 "무엇이 의존성 줄인가" 의 판단이 둘로
    갈라져 어긋난다 — 그때 어긋나는 쪽이 조용한 쪽이다.
    """
    found: list[DependencyDeclaration] = []
    skipped: list[str] = []
    for raw_line in _strip_byte_order_mark(text).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith(_DIRECTIVE_PREFIXES):
            continue
        match = _REQUIREMENT.match(line)
        if not match:
            # 관대하게 넘어가되 **말은 한다.** 호출부가 coverage 를 낮춘다.
            skipped.append(line)
            continue
        version, resolution = _classify_spec(match.group("spec"))
        if lockfile and resolution is ResolutionKind.EXACT_PIN:
            resolution = ResolutionKind.LOCKFILE
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
    return found, skipped


def unreadable_requirement_lines(text: str) -> tuple[str, ...]:
    """이 텍스트에서 읽지 못하고 건너뛴 줄.

    :func:`parse_requirements_txt` 과 같은 스캔을 쓴다. JSON·TOML 파서는 못 읽으면
    예외를 던져 시끄럽지만, 줄 단위 형식은 한 줄씩 건너뛰므로 이렇게 따로 묻는다.
    """
    return tuple(_scan_requirements(text, None, lockfile=False)[1])


def parse_requirements_txt(
    text: str, source_path: str | None = None, *, lockfile: bool = False
) -> list[DependencyDeclaration]:
    """pip requirements 형식.

    ``lockfile=True`` 는 ``requirements.lock`` 처럼 **문법은 같은데 잠금 파일**인 경우다.
    문법으로는 ``==`` 를 보고 ``EXACT_PIN`` 이라 부르게 되는데, 잠금 파일은 그보다 강한
    사실이다 — 도구가 해석을 끝내고 적어 둔 값이기 때문이다.

    이 구분이 중복 제거에서 갈린다. ``DependencySet`` 은 같은 패키지를 **가장 신뢰도 높은
    선언**만 남기는데(``LOCKFILE`` > ``EXACT_PIN`` > ``RANGE``), 잠금 파일이 ``EXACT_PIN``
    으로 들어오면 매니페스트의 ``==`` 와 값이 같아져 **먼저 온 쪽이 이긴다.** 어느 쪽이
    이길지가 파일을 읽는 순서에 달리게 된다.
    """
    return _scan_requirements(text, source_path, lockfile=lockfile)[0]


def parse_setup_cfg(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """setuptools ``setup.cfg`` 의 ``install_requires`` 와 extras.

    같은 배포판의 ``setup.py`` 는 읽지 않는다 — 임의의 파이썬 코드라 실행하지
    않고서는 의존성을 확정할 수 없다. ``setup.cfg`` 는 선언이라 읽을 수 있고,
    그래서 이쪽만 License 검사 대상이다.

    각 줄의 문법은 requirements 와 같으므로 그 판독을 그대로 쓴다.
    """
    text = _strip_byte_order_mark(text)
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
    text = _strip_byte_order_mark(text)
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
    text = _strip_byte_order_mark(text)
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
