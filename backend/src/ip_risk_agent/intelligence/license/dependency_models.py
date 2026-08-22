"""의존성 선언의 내부 표현.

버전을 어디서 얻었는지가 판정의 신뢰도를 좌우한다. lockfile 의 확정 버전과
``>=2.0`` 같은 범위는 같은 무게로 다루면 안 된다 (Agent 3 Spec 25).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class DependencyParseError(Exception):
    """파일을 읽지 못했다. **선언이 없는 것과 다르다.**

    ## 왜 예외인가

    파서들이 깨진 입력을 삼키고 빈 목록을 돌려주고 있었다. 그래서 잘린 JSON 과 "의존성을
    쓰지 않는 파일" 이 **같은 값**이 됐다.

    ```
    깨진 TOML     → []
    깨진 JSON     → []
    선언 없는 파일 → []
    ```

    빈 목록은 실패가 아니라 사실로 취급된다. 결과가 ``SUCCEEDED`` + ``COMPLETE`` 로 올라가
    권위를 얻고, 그 파일의 라이선스 Risk 가 **전부 해소된다.** 읽지 못한 것이 "위험이
    사라졌다" 가 되는 것이다.

    돌려주는 값으로 구분하지 않고 예외로 가르는 이유는, 빈 목록을 그냥 쓰는 호출부가
    **조용히 틀리기** 때문이다. 예외는 무시하려면 무시한다고 적어야 한다.

    메시지는 개발자가 쓴 상수와 파일 이름만 담는다 — 파싱 오류 본문에는 사용자 소스가
    섞여 들어올 수 있다.
    """


class Ecosystem(str, Enum):
    PYPI = "pypi"
    NPM = "npm"


class ResolutionKind(str, Enum):
    """실제로 쓰이는 버전을 얼마나 확신할 수 있는가."""

    LOCKFILE = "LOCKFILE"      # 잠금 파일의 확정 버전. 가장 신뢰할 수 있다.
    EXACT_PIN = "EXACT_PIN"    # 매니페스트의 == 고정
    RANGE = "RANGE"            # 범위 지정. 실제 설치본은 다를 수 있다.
    UNRESOLVED = "UNRESOLVED"  # 버전 정보 없음


# 신뢰도 순서. 같은 패키지가 여러 파일에 나오면 높은 쪽을 채택한다.
_PRIORITY = {
    ResolutionKind.LOCKFILE: 3,
    ResolutionKind.EXACT_PIN: 2,
    ResolutionKind.RANGE: 1,
    ResolutionKind.UNRESOLVED: 0,
}

# PEP 503. PyPI 는 - _ . 을 구분하지 않는다.
_PYPI_SEPARATORS = re.compile(r"[-_.]+")


def normalize_package_name(ecosystem: Ecosystem, name: str) -> str:
    """레지스트리 기준의 정규 이름.

    PyMuPDF 와 pymupdf 를 다른 패키지로 세면 같은 위험을 두 번 보고하게 된다.
    """
    cleaned = name.strip()
    if ecosystem is Ecosystem.PYPI:
        return _PYPI_SEPARATORS.sub("-", cleaned).lower()
    # npm 은 스코프(@scope/name)를 유지하되 대소문자만 낮춘다.
    return cleaned.lower()


@dataclass(frozen=True)
class DependencyDeclaration:
    """한 파일에서 읽어낸 의존성 하나."""

    ecosystem: Ecosystem
    name: str
    version: str | None = None
    resolution: ResolutionKind = ResolutionKind.UNRESOLVED
    raw_spec: str | None = None
    source_path: str | None = None

    @property
    def key(self) -> tuple[Ecosystem, str]:
        return (self.ecosystem, self.name)

    @property
    def is_resolved(self) -> bool:
        return self.version is not None and self.resolution in (
            ResolutionKind.LOCKFILE,
            ResolutionKind.EXACT_PIN,
        )

    def uncertainty_flags(self) -> list[str]:
        """Contract 의 ``uncertainty_flags`` 에 실을 값.

        범위 지정을 최신 버전으로 단정하지 않는다. 모른다는 사실을 남긴다.
        """
        if self.resolution is ResolutionKind.UNRESOLVED:
            return ["VERSION_UNRESOLVED"]
        if self.resolution is ResolutionKind.RANGE:
            return ["VERSION_RANGE_NOT_PINNED"]
        return []


@dataclass
class DependencySet:
    """여러 파일에서 모은 의존성. 같은 패키지는 가장 신뢰도 높은 선언만 남긴다."""

    declarations: dict[tuple[Ecosystem, str], DependencyDeclaration] = field(
        default_factory=dict
    )

    def add(self, declaration: DependencyDeclaration) -> None:
        existing = self.declarations.get(declaration.key)
        if existing is None or _PRIORITY[declaration.resolution] > _PRIORITY[existing.resolution]:
            self.declarations[declaration.key] = declaration

    def extend(self, declarations: list[DependencyDeclaration]) -> None:
        for declaration in declarations:
            self.add(declaration)

    def items(self) -> list[DependencyDeclaration]:
        """결정론적 순서. 결과 비교가 가능해야 한다."""
        return sorted(
            self.declarations.values(), key=lambda d: (d.ecosystem.value, d.name)
        )

    def __len__(self) -> int:
        return len(self.declarations)
