"""소스에 들어 있는 ``.ipriskignore``.

문법과 매칭은 :mod:`ip_risk_agent.core.security.ignore_patterns` 가 정한다. 예전에는
여기서 ``fnmatch`` 로 따로 판단했고, 그래서 **같은 파일이 두 번 다르게 평가됐다** —
커넥터는 저장소 상대 경로로 ``fnmatch``, 게이트는 마운트 절대 경로로 정규식이었다.
사람이 ``node_modules`` 라고 적으면 커넥터는 조용히 아무것도 거르지 않았다 (§9.1).
"""

from __future__ import annotations

from ip_risk_agent.core.security.ignore_patterns import (
    IgnorePatternError,
    IgnoreRule,
    is_ignored,
    parse_patterns,
)


def parse_ipriskignore(content: str) -> tuple[IgnoreRule, ...]:
    """본문을 규칙으로 읽는다. 읽을 수 없는 줄은 :class:`IgnorePatternError` 다."""
    return parse_patterns(content)


def is_denied_by_ipriskignore(path: str, rules: tuple[IgnoreRule, ...]) -> bool:
    """저장소 뿌리 기준의 상대 경로가 걸리는가."""
    return is_ignored(path, rules)


__all__ = [
    "IgnorePatternError",
    "is_denied_by_ipriskignore",
    "parse_ipriskignore",
]
