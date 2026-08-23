"""제외 패턴을 해석하는 규칙 하나.

## 왜 한 곳에 두는가

거르는 수단이 셋인데 **매처가 셋이었고 서로 달랐다.**

| 수단 | 예전 구현 | 안 맞으면 |
|---|---|---|
| 소스의 ``.ipriskignore`` | ``fnmatch(path, pattern)`` | **조용히 0 개** |
| workspace ``global_ignore_text`` | 정규식 ``fullmatch``, 선행 ``/`` 필수 | ``POLICY_INVALID`` |
| tracking scope ``exclude_patterns`` | ``fnmatch`` | **조용히 0 개** |

실측(`/backend/node_modules/a/b.js`)에서 **두 곳 모두에서 동작하는 문자열이 하나도
없었다.** 그리고 사람이 가장 자연스럽게 적는 ``node_modules`` 는 어느 쪽에서도 안
걸렸다 — 한쪽은 오류로 보이기라도 하지만 ``.ipriskignore`` 는 조용히 아무것도 거르지
않는다. **제외 목록을 적어 두고 다 걸러진다고 믿는 상태**가 된다.

같은 ``.ipriskignore`` 파일이 두 번 평가되기까지 했다. 커넥터는 저장소 상대 경로로
``fnmatch`` 했고, 게이트는 같은 파일을 마운트 절대 경로로 정규식 대조했다.

비용이 여기 달려 있다. 특허 경로 파일 하나가 KIPRIS 를 최대 11 회 쓰고 무료 한도는
월 1,000 회다. 이 저장소를 Local 로 마운트하면 한도의 **228 배**가 나온다 (§9.1).

## 무엇으로 통일했는가

**gitignore 문법이다.** 파일 이름이 ``.ipriskignore`` 이고 사람들은 ``.gitignore`` 를
안다. ``node_modules`` 라고 적으면 걸려야 한다 — 그것이 이 결함의 전부였다.

* ``/`` 가 없는 패턴은 **어느 깊이에서나** 맞는다. ``node_modules`` 는
  ``a/b/node_modules/c.js`` 를 거른다.
* ``/`` 를 품은 패턴은 **마운트 뿌리에 고정**된다. ``src/*.py`` 는 ``a/src/x.py`` 를
  거르지 않는다.
* 끝의 ``/`` 는 디렉터리를 뜻한다. 그 아래 전부가 걸린다.
* ``*`` 는 ``/`` 를 넘지 않고 ``**`` 는 넘는다.

**경로는 마운트 뿌리 기준이다.** 커넥터는 저장소 상대 경로를 그대로 넘기고, 게이트는
마운트 별칭을 떼고 넘긴다. 그래야 같은 문자열이 두 곳에서 같은 뜻이 된다.

## 부정(``!``)은 받지 않는다

이 목록은 **거르기 전용**이다. 되살리는 규칙이 섞이면 "이 패턴이 무엇을 걸렀는가" 를
줄 단위로 따질 수 없게 되고, 비용 통제 수단으로 못 쓴다. 예전 게이트도 같은 이유로
거부했다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ip_risk_agent.core.common import DomainInvariantError


class IgnorePatternError(DomainInvariantError):
    """패턴을 읽을 수 없다. 조용히 넘기지 않는다 (§9.1)."""


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    """패턴 하나. 원문을 함께 들고 다닌다 — 무엇이 걸렀는지 말해야 하기 때문이다."""

    pattern: str
    expression: re.Pattern[str]

    def matches(self, relative_path: str) -> bool:
        return self.expression.fullmatch(relative_path.casefold()) is not None


#: 빌드 산출물과 의존성 트리. 이것들이 없으면 Local 마운트가 한도의 228 배를 쓴다.
#:
#: GitHub 은 추적 파일만 보므로 `.gitignore` 가 대신 걸러 준다. **Local 은 디스크를
#: 본다** — 그 차이가 50 배다 (§9.1).
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git/",
    ".hg/",
    ".svn/",
    "node_modules/",
    ".venv/",
    "venv/",
    "vendor/",
    "dist/",
    "build/",
    "target/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    ".gradle/",
    ".next/",
    ".nuxt/",
    ".terraform/",
    "site-packages/",
    "*.min.js",
    "*.map",
    "*.lock.json",
)


def normalize_relative_path(path: str) -> str:
    """경로를 마운트 뿌리 기준의 상대 경로로 만든다.

    게이트는 ``/{별칭}/{나머지}`` 를 들고 있고 커넥터는 저장소 상대 경로를 들고 있다.
    같은 문자열이 두 곳에서 같은 뜻이 되려면 여기서 만나야 한다.
    """
    normalized = path.replace("\\", "/").strip("/")
    if "\x00" in normalized:
        raise IgnorePatternError("path contains a null byte")
    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise IgnorePatternError("path contains invalid traversal")
    return "/".join(parts)


def strip_mount_alias(logical_path: str) -> str:
    """``/{별칭}/{나머지}`` 에서 별칭을 뗀다.

    패턴은 마운트 뿌리 기준이므로 별칭은 대조 대상이 아니다. 별칭까지 포함해 맞추면
    같은 패턴이 마운트 이름에 따라 걸리기도 하고 안 걸리기도 한다.
    """
    relative = normalize_relative_path(logical_path)
    _, _, rest = relative.partition("/")
    return rest


def parse_patterns(text: str) -> tuple[IgnoreRule, ...]:
    """``.ipriskignore`` 본문을 규칙으로 읽는다.

    빈 줄과 ``#`` 주석은 넘긴다. 그 밖에 읽을 수 없는 줄은 **예외**다 — 조용히
    넘기면 목록을 적어 두고 걸러진다고 믿는 상태가 된다.
    """
    rules: list[IgnoreRule] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        pattern = raw_line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        rules.append(compile_pattern(pattern, line_number=line_number))
    return tuple(rules)


def compile_pattern(pattern: str, *, line_number: int | None = None) -> IgnoreRule:
    """패턴 하나를 규칙으로 만든다."""
    where = "" if line_number is None else f" at line {line_number}"
    if pattern.startswith("!"):
        raise IgnorePatternError(f"negation is unsupported{where}")
    if "\x00" in pattern:
        raise IgnorePatternError(f"pattern is invalid{where}")
    body = pattern.replace("\\", "/")
    if "//" in body:
        raise IgnorePatternError(f"pattern is invalid{where}")
    if any(part in {".", ".."} for part in body.split("/")):
        raise IgnorePatternError(f"pattern traversal is invalid{where}")

    directory_only = body.endswith("/")
    trimmed = body.rstrip("/")
    if not trimmed:
        raise IgnorePatternError(f"pattern is empty{where}")

    # 선행 `/` 는 "뿌리에 고정" 이라는 뜻이지 필수 표기가 아니다. 예전 게이트는 이것을
    # 요구해서 `node_modules` 를 오류로 거부했다.
    anchored = trimmed.startswith("/") or "/" in trimmed.strip("/")
    trimmed = trimmed.lstrip("/")

    prefix = "" if anchored else "(?:.*/)?"
    expression = prefix + _glob_expression(trimmed.casefold())
    # 끝의 `/` 는 "디렉터리" 라는 뜻이다. 그 아래 전부가 걸리되, **같은 이름의
    # 파일**은 걸리지 않는다 — `dist/` 는 `dist/a.js` 를 거르지만 `dist` 라는 파일은
    # 거르지 않는다. 끝의 `/` 가 없으면 둘 다 거른다.
    suffix = "/.*" if directory_only else "(?:/.*)?"
    return IgnoreRule(pattern=pattern, expression=re.compile(f"^{expression}{suffix}$"))


def first_match(relative_path: str, rules: tuple[IgnoreRule, ...]) -> IgnoreRule | None:
    """이 경로를 처음 거른 규칙. 없으면 ``None``.

    참·거짓이 아니라 **규칙**을 돌려준다. 무엇이 걸렀는지 말할 수 있어야 사용자가
    목록을 고칠 수 있고, 아무것도 안 거른 규칙도 셀 수 있다 (§9.1).
    """
    candidate = normalize_relative_path(relative_path)
    for rule in rules:
        if rule.matches(candidate):
            return rule
    return None


def is_ignored(relative_path: str, rules: tuple[IgnoreRule, ...]) -> bool:
    return first_match(relative_path, rules) is not None


def _glob_expression(pattern: str) -> str:
    expression: list[str] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    expression.append("(?:.*/)?")
                    index += 1
                else:
                    expression.append(".*")
                continue
            expression.append("[^/]*")
        elif character == "?":
            expression.append("[^/]")
        else:
            expression.append(re.escape(character))
        index += 1
    return "".join(expression)


__all__ = [
    "DEFAULT_IGNORE_PATTERNS",
    "IgnorePatternError",
    "IgnoreRule",
    "compile_pattern",
    "first_match",
    "is_ignored",
    "normalize_relative_path",
    "parse_patterns",
    "strip_mount_alias",
]
