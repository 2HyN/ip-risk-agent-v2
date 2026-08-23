"""게이트가 쓰는 제외 판정.

문법과 매칭은 :mod:`ip_risk_agent.core.security.ignore_patterns` 가 정한다. 여기서는
**게이트가 들고 있는 경로 모양**만 맞춰 준다 — 게이트의 ``logical_path`` 는
``/{별칭}/{나머지}`` 이고, 패턴은 마운트 뿌리 기준이다.

예전에는 여기가 선행 ``/`` 를 요구해서 ``node_modules`` 를 오류로 거부했고, 커넥터
쪽은 같은 문자열을 조용히 통과시켰다. 두 곳 모두에서 동작하는 문자열이 하나도
없었다 (§9.1).
"""

from __future__ import annotations

from ip_risk_agent.core.security.ignore_patterns import (
    IgnorePatternError,
    IgnoreRule,
    first_match,
    parse_patterns,
    strip_mount_alias,
)

#: 예전 이름. 부르는 쪽이 이 이름으로 잡고 있다.
IgnorePolicyError = IgnorePatternError


def parse_ipriskignore(text: str) -> tuple[IgnoreRule, ...]:
    return parse_patterns(text)


def is_ignored(logical_path: str, rules: tuple[IgnoreRule, ...]) -> bool:
    """마운트 절대 경로가 걸리는가.

    별칭은 대조하지 않는다. 별칭까지 맞추면 같은 패턴이 **마운트 이름에 따라**
    걸리기도 하고 안 걸리기도 한다.
    """
    if not logical_path.startswith("/"):
        raise IgnorePatternError("logical path must be canonical and mount-absolute")
    return first_match(strip_mount_alias(logical_path), rules) is not None


__all__ = [
    "IgnorePolicyError",
    "IgnoreRule",
    "is_ignored",
    "parse_ipriskignore",
]
