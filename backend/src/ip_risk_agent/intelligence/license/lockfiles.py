"""잠금 파일 파서.

잠금 파일에는 실제로 설치되는 버전이 적혀 있다. 매니페스트의 범위 지정보다 항상
우선한다 (Agent 3 Spec 25).
"""

from __future__ import annotations

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


def _npm_name_from_path(path: str) -> str | None:
    """``node_modules/@scope/pkg/node_modules/dep`` 에서 마지막 패키지 이름.

    lockfile v3 는 설치 경로를 키로 쓴다. 중첩 설치가 있으면 마지막 것이 그 패키지다.
    """
    marker = "node_modules/"
    index = path.rfind(marker)
    if index < 0:
        return None
    name = path[index + len(marker):].strip("/")
    return name or None


def parse_package_lock_json(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """npm ``package-lock.json``. v2/v3 의 ``packages`` 와 v1 의 ``dependencies``."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DependencyParseError("package-lock.json is not readable") from exc
    if not isinstance(document, dict):
        raise DependencyParseError("package-lock.json is not an object")

    found: list[DependencyDeclaration] = []

    packages = document.get("packages")
    if isinstance(packages, dict):
        for path, entry in packages.items():
            if not path or not isinstance(entry, dict):
                continue  # "" 는 프로젝트 자신이다.
            name = entry.get("name") if "node_modules/" not in path else _npm_name_from_path(path)
            version = entry.get("version")
            if not name or not isinstance(version, str):
                continue
            found.append(
                DependencyDeclaration(
                    ecosystem=Ecosystem.NPM,
                    name=normalize_package_name(Ecosystem.NPM, str(name)),
                    version=version,
                    resolution=ResolutionKind.LOCKFILE,
                    raw_spec=path,
                    source_path=source_path,
                )
            )

    if not found:
        legacy = document.get("dependencies")
        if isinstance(legacy, dict):
            for name, entry in legacy.items():
                version = entry.get("version") if isinstance(entry, dict) else None
                if not isinstance(version, str):
                    continue
                found.append(
                    DependencyDeclaration(
                        ecosystem=Ecosystem.NPM,
                        name=normalize_package_name(Ecosystem.NPM, name),
                        version=version,
                        resolution=ResolutionKind.LOCKFILE,
                        raw_spec=f"{name}@{version}",
                        source_path=source_path,
                    )
                )
    return found


def parse_uv_lock(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """uv ``uv.lock``. ``[[package]]`` 마다 name 과 version 이 온다."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DependencyParseError("uv.lock is not readable") from exc

    found: list[DependencyDeclaration] = []
    for entry in document.get("package") or []:
        if not isinstance(entry, dict):
            continue
        name, version = entry.get("name"), entry.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        found.append(
            DependencyDeclaration(
                ecosystem=Ecosystem.PYPI,
                name=normalize_package_name(Ecosystem.PYPI, name),
                version=version,
                resolution=ResolutionKind.LOCKFILE,
                raw_spec=f"{name}=={version}",
                source_path=source_path,
            )
        )
    return found


def parse_poetry_lock(text: str, source_path: str | None = None) -> list[DependencyDeclaration]:
    """poetry ``poetry.lock``. 구조는 uv.lock 과 같은 ``[[package]]`` 배열이다."""
    return parse_uv_lock(text, source_path)


# 논리 경로 -> 파서. 파일명으로만 판단한다. 경로 형태는 Source 마다 다르다.
_PARSERS: tuple[tuple[re.Pattern[str], object], ...] = (
    (re.compile(r"(^|/)package-lock\.json$", re.I), parse_package_lock_json),
    (re.compile(r"(^|/)uv\.lock$", re.I), parse_uv_lock),
    (re.compile(r"(^|/)poetry\.lock$", re.I), parse_poetry_lock),
)


def parser_for(logical_path: str):
    """경로에 맞는 잠금 파일 파서. 없으면 None."""
    for pattern, parser in _PARSERS:
        if pattern.search(logical_path):
            return parser
    return None
