from __future__ import annotations

from ip_risk_agent.connectors.common.ipriskignore import (
    is_denied_by_ipriskignore,
    parse_ipriskignore,
)


def test_parse_ignores_blank_lines_and_comments():
    content = "\n# comment\n\ncustomer-data/**\n\n# another comment\n*.pem\n"
    patterns = parse_ipriskignore(content)
    assert patterns == ["customer-data/**", "*.pem"]


def test_parse_strips_whitespace():
    content = "  secrets/**  \n"
    patterns = parse_ipriskignore(content)
    assert patterns == ["secrets/**"]


def test_is_denied_matches_pattern():
    assert is_denied_by_ipriskignore("customer-data/file.csv", ["customer-data/**"]) is True


def test_is_denied_no_match():
    assert is_denied_by_ipriskignore("src/main.py", ["customer-data/**"]) is False


def test_is_denied_empty_patterns_never_denies():
    assert is_denied_by_ipriskignore("anything.py", []) is False


def test_is_denied_extension_pattern():
    assert is_denied_by_ipriskignore("backend/secrets/key.pem", ["*.pem"]) is True
