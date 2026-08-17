"""SPDX 식별자 정규화와 표현식 파싱.

``MIT OR GPL-3.0`` 과 ``MIT AND GPL-3.0`` 은 의무가 완전히 다르다. 앞의 것은 MIT 만
지키면 되고, 뒤의 것은 둘 다 지켜야 한다. 문자열에서 식별자만 긁어 가장 무거운 것을
고르면 두 경우가 같아진다. 그래서 실제로 파싱한다 (Agent 3 Spec 27).

문법 (SPDX 2.3 중 실제로 마주치는 범위):

    expression := compound ( ("AND" | "OR") compound )*
    compound   := "(" expression ")" | simple ( "WITH" exception )?
    simple     := identifier ("+")?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 정책 테이블과 대조할 때 쓰는 SPDX 데이터 기준. 바뀌면 policy_version 도 올린다.
SPDX_SNAPSHOT_VERSION = "spdx-3.24-subset"

_TOKEN = re.compile(r"\(|\)|[A-Za-z0-9.+\-]+")
_OPERATORS = {"AND", "OR", "WITH"}

# 자유 서술 라이선스 문자열 -> SPDX. 구체적인 것을 앞에 둔다.
# deps.dev 가 non-standard 를 돌려줄 때 레지스트리 원문을 이 표로 되살린다.
_TEXT_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\baffero\b|\bagpl\b", re.I), "AGPL-3.0-only"),
    (re.compile(r"\blgpl\s*-?\s*v?3", re.I), "LGPL-3.0-only"),
    (re.compile(r"\blgpl\b|lesser\s+general\s+public", re.I), "LGPL-2.1-only"),
    (re.compile(r"\bgpl\s*-?\s*v?3|general\s+public\s+license\s+v?\s*3", re.I), "GPL-3.0-only"),
    (re.compile(r"\bgpl\s*-?\s*v?2|general\s+public\s+license\s+v?\s*2", re.I), "GPL-2.0-only"),
    (re.compile(r"\bmpl\b|mozilla\s+public", re.I), "MPL-2.0"),
    (re.compile(r"\bepl\b|eclipse\s+public", re.I), "EPL-2.0"),
    (re.compile(r"\bapache\b", re.I), "Apache-2.0"),
    (re.compile(r"\bbsd\b.*\b3\b|3[-\s]clause", re.I), "BSD-3-Clause"),
    (re.compile(r"\bbsd\b.*\b2\b|2[-\s]clause", re.I), "BSD-2-Clause"),
    (re.compile(r"\bbsd\b", re.I), "BSD-3-Clause"),
    (re.compile(r"\bisc\b", re.I), "ISC"),
    (re.compile(r"\bmit\b", re.I), "MIT"),
    (re.compile(r"\bunlicen[cs]e\b|public\s+domain", re.I), "Unlicense"),
    (re.compile(r"\bzlib\b", re.I), "Zlib"),
)

# 대소문자·구두점만 다른 표기. 등록된 식별자로 되돌린다.
_ID_ALIASES: dict[str, str] = {
    "apache 2.0": "Apache-2.0",
    "apache2": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apachev2": "Apache-2.0",
    "bsd": "BSD-3-Clause",
    "bsd3": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause",
    "bsd2": "BSD-2-Clause",
    "gpl2": "GPL-2.0-only",
    "gpl-2": "GPL-2.0-only",
    "gplv2": "GPL-2.0-only",
    "gpl3": "GPL-3.0-only",
    "gpl-3": "GPL-3.0-only",
    "gplv3": "GPL-3.0-only",
    "lgpl": "LGPL-2.1-only",
    "lgplv3": "LGPL-3.0-only",
    "agpl": "AGPL-3.0-only",
    "agplv3": "AGPL-3.0-only",
    "mpl2": "MPL-2.0",
    "mpl-2": "MPL-2.0",
    "the unlicense": "Unlicense",
    "zlib/libpng": "Zlib",
}

# 등록된 식별자의 정규 표기. 소문자 키로 찾는다.
_CANONICAL: tuple[str, ...] = (
    "0BSD", "AFL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "Apache-2.0",
    "Artistic-2.0", "BSD-2-Clause", "BSD-3-Clause", "BSL-1.0", "CC0-1.0",
    "CDDL-1.0", "CDDL-1.1", "CPL-1.0", "EPL-1.0", "EPL-2.0", "EUPL-1.2",
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "ISC", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only",
    "LGPL-3.0-or-later", "MIT", "MPL-1.1", "MPL-2.0", "MS-PL", "MS-RL",
    "NCSA", "OFL-1.1", "OSL-3.0", "PostgreSQL", "Python-2.0", "SSPL-1.0",
    "Unlicense", "W3C", "WTFPL", "X11", "Zlib", "ZPL-2.1",
)
_CANONICAL_BY_LOWER = {name.lower(): name for name in _CANONICAL}

UNKNOWN_LICENSE = "UNKNOWN"

# deps.dev 와 레지스트리가 "모른다"는 뜻으로 쓰는 값들.
_NON_STANDARD = frozenset({"", "non-standard", "unknown", "none", "other", "proprietary"})


def canonicalize(identifier: str) -> str:
    """단일 식별자를 등록된 표기로 되돌린다. 모르면 :data:`UNKNOWN_LICENSE`."""
    raw = identifier.strip()
    if raw.lower() in _NON_STANDARD:
        return UNKNOWN_LICENSE

    # "GPL-2.0+" 은 "-or-later" 의 옛 표기다.
    plus = raw.endswith("+")
    base = raw[:-1] if plus else raw
    low = base.lower()

    resolved = _CANONICAL_BY_LOWER.get(low) or _ID_ALIASES.get(low)
    if resolved is None:
        # "GPL-2.0" 처럼 접미사가 빠진 표기는 -only 로 본다. SPDX 권고와 같다.
        resolved = _CANONICAL_BY_LOWER.get(f"{low}-only")
    if resolved is None:
        return UNKNOWN_LICENSE
    if plus and resolved.endswith("-only"):
        resolved = resolved[: -len("-only")] + "-or-later"
    return resolved


def from_free_text(text: str) -> str:
    """레지스트리의 자유 서술 문자열에서 식별자를 추정한다.

    PyMuPDF 의 "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial" 처럼
    자동 매핑이 실패한 값을 되살리는 경로다. 추정이므로 호출부에서
    uncertainty 로 표시해야 한다.
    """
    if not text or text.strip().lower() in _NON_STANDARD:
        return UNKNOWN_LICENSE
    direct = canonicalize(text)
    if direct is not UNKNOWN_LICENSE and direct != UNKNOWN_LICENSE:
        return direct
    for pattern, identifier in _TEXT_ALIASES:
        if pattern.search(text):
            return identifier
    return UNKNOWN_LICENSE


# ------------------------------------------------------------------ 표현식


@dataclass(frozen=True)
class LicenseNode:
    """단일 라이선스. ``WITH`` 예외를 달 수 있다."""

    identifier: str
    exception: str | None = None

    def __str__(self) -> str:
        return f"{self.identifier} WITH {self.exception}" if self.exception else self.identifier

    @property
    def is_unknown(self) -> bool:
        return self.identifier == UNKNOWN_LICENSE


@dataclass(frozen=True)
class AndNode:
    """모든 조건이 함께 적용된다."""

    operands: tuple["ExpressionNode", ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        return " AND ".join(_wrap(op) for op in self.operands)


@dataclass(frozen=True)
class OrNode:
    """수취인이 하나를 고를 수 있다."""

    operands: tuple["ExpressionNode", ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        return " OR ".join(_wrap(op) for op in self.operands)


ExpressionNode = LicenseNode | AndNode | OrNode


def _wrap(node: ExpressionNode) -> str:
    """중첩된 복합 노드만 괄호로 감싼다."""
    return f"({node})" if isinstance(node, (AndNode, OrNode)) else str(node)


class SpdxParseError(ValueError):
    """표현식이 문법에 맞지 않는다."""


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> str:
        token = self._peek()
        if token is None:
            raise SpdxParseError("unexpected end of expression")
        self._pos += 1
        return token

    def parse(self) -> ExpressionNode:
        node = self._parse_or()
        if self._peek() is not None:
            raise SpdxParseError(f"unexpected token: {self._peek()!r}")
        return node

    def _parse_or(self) -> ExpressionNode:
        operands = [self._parse_and()]
        while (token := self._peek()) and token.upper() == "OR":
            self._next()
            operands.append(self._parse_and())
        return operands[0] if len(operands) == 1 else OrNode(tuple(operands))

    def _parse_and(self) -> ExpressionNode:
        operands = [self._parse_atom()]
        while (token := self._peek()) and token.upper() == "AND":
            self._next()
            operands.append(self._parse_atom())
        return operands[0] if len(operands) == 1 else AndNode(tuple(operands))

    def _parse_atom(self) -> ExpressionNode:
        token = self._next()
        if token == "(":
            inner = self._parse_or()
            if self._next() != ")":
                raise SpdxParseError("unbalanced parenthesis")
            return inner
        if token == ")" or token.upper() in _OPERATORS:
            raise SpdxParseError(f"unexpected token: {token!r}")

        identifier = canonicalize(token)
        exception: str | None = None
        if (nxt := self._peek()) and nxt.upper() == "WITH":
            self._next()
            exception = self._next()
        return LicenseNode(identifier=identifier, exception=exception)


def parse_expression(expression: str) -> ExpressionNode:
    """SPDX 표현식을 구조로 바꾼다.

    파싱에 실패하면 자유 서술로 보고 한 번 더 추정한다. 레지스트리 값이
    표현식이 아닌 설명문인 경우가 흔하다.
    """
    tokens = _TOKEN.findall(expression or "")
    if not tokens:
        return LicenseNode(UNKNOWN_LICENSE)
    try:
        return _Parser(tokens).parse()
    except SpdxParseError:
        return LicenseNode(from_free_text(expression))


def leaves(node: ExpressionNode) -> list[LicenseNode]:
    """표현식에 등장하는 모든 단일 라이선스. 등장 순서를 유지한다."""
    if isinstance(node, LicenseNode):
        return [node]
    collected: list[LicenseNode] = []
    for operand in node.operands:
        collected.extend(leaves(operand))
    return collected


def normalize(expression: str) -> str:
    """표기를 정규화한 표현식 문자열. Contract 에 싣는 값이다."""
    return str(parse_expression(expression))
