"""소스의 ``.ipriskignore`` 는 공용 매처를 쓴다 (§9.1 · 결함 25).

예전에는 여기서 ``fnmatch`` 로 따로 판단했다. 그래서 **같은 파일이 두 번 다르게**
평가됐다 — 커넥터는 저장소 상대 경로로 ``fnmatch``, 게이트는 마운트 절대 경로로
정규식이었다.
"""

from __future__ import annotations

import pytest

from ip_risk_agent.connectors.common.ipriskignore import (
    IgnorePatternError,
    is_denied_by_ipriskignore,
    parse_ipriskignore,
)


def _denies(pattern: str, path: str) -> bool:
    return is_denied_by_ipriskignore(path, parse_ipriskignore(pattern))


def test_parse_ignores_blank_lines_and_comments():
    rules = parse_ipriskignore("\n# comment\n\ncustomer-data/**\n\n# another\n*.pem\n")
    assert [rule.pattern for rule in rules] == ["customer-data/**", "*.pem"]


def test_parse_strips_whitespace():
    assert [rule.pattern for rule in parse_ipriskignore("  secrets/**  \n")] == [
        "secrets/**"
    ]


def test_is_denied_matches_pattern():
    assert _denies("customer-data/**", "customer-data/file.csv")


def test_is_denied_no_match():
    assert not _denies("customer-data/**", "src/main.py")


def test_is_denied_empty_patterns_never_denies():
    assert not is_denied_by_ipriskignore("anything.py", ())


def test_is_denied_extension_pattern():
    assert _denies("*.pem", "backend/secrets/key.pem")


def test_the_word_a_person_would_actually_write_now_filters():
    """이것이 결함 25 의 전부다.

    실측에서 ``node_modules`` 는 **어느 수단에서도 걸리지 않았다.** 게이트는 오류로
    보여 주기라도 했지만 여기서는 조용히 통과했다 — 제외 목록을 적어 두고 다 걸러진다고
    믿는 상태가 된다. 특허 경로 파일 하나가 KIPRIS 를 최대 11 회 쓰고 무료 한도는 월
    1,000 회다.
    """
    assert _denies("node_modules", "backend/node_modules/a/b.js")
    assert _denies("node_modules", "node_modules/a.js")
    assert _denies("node_modules/", "backend/node_modules/a/b.js")


@pytest.mark.parametrize(
    "pattern", ("node_modules", "**/node_modules/**", "/**/node_modules/**")
)
def test_the_shapes_people_write_all_reach_the_same_place(pattern: str) -> None:
    """예전에는 이 셋 중 **하나만** 걸렸고, 그것도 수단마다 달랐다."""
    assert _denies(pattern, "backend/node_modules/a/b.js")


def test_a_pattern_with_a_slash_is_anchored_to_the_mount_root():
    """``/`` 를 품은 패턴은 아무 데서나 맞으면 안 된다. gitignore 와 같다."""
    assert _denies("src/*.py", "src/main.py")
    assert not _denies("src/*.py", "backend/src/main.py")


def test_a_trailing_slash_means_a_directory():
    assert _denies("dist/", "dist/bundle.js")
    assert not _denies("dist/", "dist")
    # 끝의 `/` 가 없으면 같은 이름의 파일도 걸린다.
    assert _denies("dist", "dist")


def test_an_unreadable_pattern_is_not_swallowed():
    """조용히 넘기면 목록을 적어 두고 걸러진다고 믿는 상태가 된다 (§9.1)."""
    with pytest.raises(IgnorePatternError):
        parse_ipriskignore("!keep-me")
    with pytest.raises(IgnorePatternError):
        parse_ipriskignore("../escape")
