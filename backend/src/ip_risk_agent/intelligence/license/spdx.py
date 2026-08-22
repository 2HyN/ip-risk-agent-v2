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

from . import spdx_data

# 정책 테이블과 대조할 때 쓰는 SPDX 데이터 기준. 바뀌면 policy_version 도 올린다.
SPDX_SNAPSHOT_VERSION = f"spdx-{spdx_data.SPDX_LIST_VERSION}"

# ``:`` 는 ``DocumentRef-x:LicenseRef-y`` 하나를 위해 있다. SPDX 표현식에서 그 밖에
# 쓰이지 않으므로 다른 토큰을 흐트러뜨리지 않는다.
_TOKEN = re.compile(r"\(|\)|[A-Za-z0-9.+:\-]+")
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

#: 등록된 식별자 전부. **어휘는 넓게, 판단은 좁게.**
#:
#: 예전에는 정책 표에 있는 42 개만 여기 있었고, 그래서 ``BUSL-1.1`` 처럼 **등록된 진짜
#: 식별자가 저장 경계 이전에 ``UNKNOWN`` 으로 소거**됐다. 소거된 뒤에는 정책 표를 넓혀도
#: 구제할 수 없다 — 원문이 어디에도 남지 않기 때문이다.
#:
#: 이제 어휘는 SPDX 전부이고, "어느 검토 등급인가" 만 :mod:`.policy` 가 따로 정한다.
#: 정책 표에 없는 식별자는 등급이 ``UNKNOWN`` 이 되지만 **문자열은 살아남는다.**
_CANONICAL: tuple[str, ...] = spdx_data.LICENSE_IDS
_CANONICAL_BY_LOWER = {name.lower(): name for name in _CANONICAL}

_EXCEPTION_BY_LOWER = {name.lower(): name for name in spdx_data.EXCEPTION_IDS}

#: ``LicenseRef-Acme-Internal`` 처럼 SPDX 목록 밖을 가리키는 사용자 정의 참조.
#: ``DocumentRef-x:LicenseRef-y`` 형태도 문법상 허용된다.
_LICENSE_REF = re.compile(r"^(?:DocumentRef-[A-Za-z0-9.\-]+:)?LicenseRef-[A-Za-z0-9.\-]+$")

#: SPDX 가 폐기한 표기를 현행 표기로 옮긴다. 값은 ``(식별자, 딸려 오는 예외)``.
#:
#: 폐기된 것도 등록된 식별자이므로 소거하지 않는다. 다만 그대로 두면 현행 표기를 쓰는 정책
#: 표와 어긋나 조용히 ``UNKNOWN`` 등급이 되므로 옮긴다.
#:
#: **기계적으로 유도되는 것만 적었다.** ``Net-SNMP`` 와 ``Nunit`` 은 SPDX 가 대체 식별자를
#: 주지 않아 비워 두었다 — 추측해서 옮기면 없는 판단을 만들어 낸다.
_DEPRECATED_REPLACEMENT: dict[str, tuple[str, str | None]] = {
    # 접미사가 빠진 옛 표기
    "agpl-1.0": ("AGPL-1.0-only", None),
    "agpl-3.0": ("AGPL-3.0-only", None),
    "gfdl-1.1": ("GFDL-1.1-only", None),
    "gfdl-1.2": ("GFDL-1.2-only", None),
    "gfdl-1.3": ("GFDL-1.3-only", None),
    "gpl-1.0": ("GPL-1.0-only", None),
    "gpl-2.0": ("GPL-2.0-only", None),
    "gpl-3.0": ("GPL-3.0-only", None),
    "lgpl-2.0": ("LGPL-2.0-only", None),
    "lgpl-2.1": ("LGPL-2.1-only", None),
    "lgpl-3.0": ("LGPL-3.0-only", None),
    # "+" 를 붙인 옛 표기. 그 자체가 등록된 폐기 식별자다.
    "gpl-1.0+": ("GPL-1.0-or-later", None),
    "gpl-2.0+": ("GPL-2.0-or-later", None),
    "gpl-3.0+": ("GPL-3.0-or-later", None),
    "lgpl-2.0+": ("LGPL-2.0-or-later", None),
    "lgpl-2.1+": ("LGPL-2.1-or-later", None),
    "lgpl-3.0+": ("LGPL-3.0-or-later", None),
    # 예외를 이름 안에 품고 있던 합성 표기. 지금은 WITH 로 쓴다.
    "gpl-2.0-with-gcc-exception": ("GPL-2.0-only", "GCC-exception-2.0"),
    "gpl-2.0-with-autoconf-exception": ("GPL-2.0-only", "Autoconf-exception-2.0"),
    "gpl-2.0-with-bison-exception": ("GPL-2.0-only", "Bison-exception-2.2"),
    "gpl-2.0-with-classpath-exception": ("GPL-2.0-only", "Classpath-exception-2.0"),
    "gpl-2.0-with-font-exception": ("GPL-2.0-only", "Font-exception-2.0"),
    "gpl-3.0-with-gcc-exception": ("GPL-3.0-only", "GCC-exception-3.1"),
    "gpl-3.0-with-autoconf-exception": ("GPL-3.0-only", "Autoconf-exception-3.0"),
    "ecos-2.0": ("GPL-2.0-or-later", "eCos-exception-2.0"),
    "wxwindows": ("LGPL-2.0-or-later", "WxWindows-exception-3.1"),
    # 이름이 바뀐 것
    "standardml-nj": ("SMLNJ", None),
    "bzip2-1.0.5": ("bzip2-1.0.6", None),
    "bsd-2-clause-netbsd": ("BSD-2-Clause", None),
    "bsd-2-clause-freebsd": ("BSD-2-Clause-Views", None),
}

UNKNOWN_LICENSE = "UNKNOWN"

# deps.dev 와 레지스트리가 "모른다"는 뜻으로 쓰는 값들.
_NON_STANDARD = frozenset({"", "non-standard", "unknown", "none", "other", "proprietary"})


def canonicalize_exception(token: str) -> str | None:
    """등록된 예외면 정규 표기를, 아니면 ``None``.

    예외 식별자는 지금까지 아무 검증도 받지 않았다. 오타든 날조든 그대로 통과해
    **맨 라이선스와 같은 판정**을 받았다. 완화 여부는 :mod:`.policy` 가 정하지만, 그 전에
    "등록된 것인가" 를 여기서 가른다.
    """
    return _EXCEPTION_BY_LOWER.get(token.strip().lower())


def _resolve(identifier: str) -> tuple[str, str | None]:
    """식별자 하나를 ``(현행 표기, 딸려 오는 예외)`` 로 푼다.

    폐기된 합성 표기(``GPL-2.0-with-classpath-exception``)가 예외를 품고 있으므로 둘을 함께
    돌려준다. 예외를 버리면 그 표기가 맨 GPL 과 같아진다.
    """
    raw = identifier.strip()
    if raw.lower() in _NON_STANDARD:
        return UNKNOWN_LICENSE, None

    # ``LicenseRef-*`` 는 SPDX 문법이 인정하는 **사용자 정의 참조**다. 목록에 없다고
    # 소거하면 "우리가 쓰는 사내 라이선스" 가 "모르는 라이선스" 와 구별되지 않는다.
    # 표기만 맞추고 그대로 둔다. 등급은 정책 표에 없으므로 UNKNOWN 이 되고, 그것이
    # 맞다 — 사내 라이선스의 의무는 우리가 알 수 없다.
    if _LICENSE_REF.match(raw):
        return raw, None

    # 폐기 표기를 먼저 본다 — "GPL-2.0+" 처럼 그 자체가 등록된 폐기 식별자라
    # 아래의 "+" 처리보다 앞서야 한다.
    replaced = _DEPRECATED_REPLACEMENT.get(raw.lower())
    if replaced is not None:
        return replaced

    # "GPL-2.0+" 은 "-or-later" 의 옛 표기다.
    plus = raw.endswith("+")
    base = raw[:-1] if plus else raw
    low = base.lower()

    resolved = _CANONICAL_BY_LOWER.get(low) or _ID_ALIASES.get(low)
    if resolved is None:
        # "GPL-2.0" 처럼 접미사가 빠진 표기는 -only 로 본다. SPDX 권고와 같다.
        resolved = _CANONICAL_BY_LOWER.get(f"{low}-only")
    if resolved is None:
        return UNKNOWN_LICENSE, None
    if plus and resolved.endswith("-only"):
        resolved = resolved[: -len("-only")] + "-or-later"
    return resolved, None


def canonicalize(identifier: str) -> str:
    """단일 식별자를 등록된 표기로 되돌린다. 모르면 :data:`UNKNOWN_LICENSE`.

    합성 폐기 표기가 품고 있던 예외는 여기서 사라진다. 예외까지 필요하면 표현식으로
    파싱한다 — :func:`parse_expression` 이 :class:`LicenseNode` 에 함께 담는다.
    """
    return _resolve(identifier)[0]


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

    @property
    def exception_is_registered(self) -> bool:
        """달린 예외가 SPDX 에 등록된 것인가.

        등록되지 않은 예외도 문자열은 그대로 둔다 (원문 보존과 같은 이유다). 다만
        :mod:`.policy` 는 이 값이 거짓이면 **어떤 완화도 주지 않는다.**
        """
        return (
            self.exception is not None
            and canonicalize_exception(self.exception) is not None
        )


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

        identifier, exception = _resolve(token)
        if (nxt := self._peek()) and nxt.upper() == "WITH":
            self._next()
            written = self._next()
            # 등록된 것이면 정규 표기로, 아니면 쓰인 그대로 둔다. 버리지 않는 이유는
            # 원문이 남아야 목록이 넓어졌을 때 다시 볼 수 있기 때문이다.
            exception = canonicalize_exception(written) or written
        return LicenseNode(identifier=identifier, exception=exception)


def try_parse_expression(expression: str) -> ExpressionNode | None:
    """표현식으로 읽히면 구조를, 아니면 None 을 돌려준다.

    추정과 파싱을 구분해야 호출부가 "추측한 값"임을 표시할 수 있다.
    :func:`parse_expression` 은 실패를 흡수하므로 그것만으로는 알 수 없다.
    """
    tokens = _TOKEN.findall(expression or "")
    if not tokens:
        return None
    try:
        return _Parser(tokens).parse()
    except SpdxParseError:
        return None


def is_all_unknown(node: ExpressionNode) -> bool:
    """등장하는 식별자가 전부 미상인가. 자유 서술 추정을 시도할 기준이다."""
    return all(leaf.is_unknown for leaf in leaves(node))


def parse_expression(expression: str) -> ExpressionNode:
    """SPDX 표현식을 구조로 바꾼다.

    파싱에 실패하면 자유 서술로 보고 한 번 더 추정한다. 레지스트리 값이
    표현식이 아닌 설명문인 경우가 흔하다.
    """
    parsed = try_parse_expression(expression)
    if parsed is None:
        return LicenseNode(from_free_text(expression))
    return parsed


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
