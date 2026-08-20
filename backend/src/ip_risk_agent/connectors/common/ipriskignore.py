"""Source-level .ipriskignore 파싱/매칭. Agent 2 Spec §18(GitHub), §28(Local).

VWS 전역 .ipriskignore(Agent 1 SecurityGate 책임)와는 다른, source 자체에
내장된 optional deny 목록이다. 우리가 재구현하는 건 이 source-level 것뿐이다.

gitignore와 완전히 동일한 문법(!negation, 디렉토리 전용 트레일링 슬래시 등)을
전부 구현하진 않고, 기존 tracking_scope에서 이미 쓰고 검증된 fnmatch 기반
글롭 매칭으로 통일했다 — 일관성 유지가 목적. 필요해지면 나중에 확장 가능.
"""

from __future__ import annotations

import fnmatch


def parse_ipriskignore(content: str) -> list[str]:
    """.ipriskignore 텍스트를 패턴 목록으로 파싱한다.
    빈 줄과 '#'로 시작하는 주석 줄은 무시한다."""

    patterns: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def is_denied_by_ipriskignore(path: str, patterns: list[str]) -> bool:
    """path가 patterns 중 하나라도 매치되면 deny."""

    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
