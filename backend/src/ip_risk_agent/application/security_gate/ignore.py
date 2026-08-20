"""Deny-only `.ipriskignore` parser and logical-path matcher."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ip_risk_agent.core.common import DomainInvariantError


class IgnorePolicyError(DomainInvariantError):
    pass


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    expression: re.Pattern[str]


def parse_ipriskignore(text: str) -> tuple[IgnoreRule, ...]:
    rules: list[IgnoreRule] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        pattern = raw_line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.startswith("!"):
            raise IgnorePolicyError(
                f".ipriskignore negation is unsupported at line {line_number}"
            )
        if not pattern.startswith("/"):
            raise IgnorePolicyError(
                f".ipriskignore pattern must be mount-absolute at line {line_number}"
            )
        if "\\" in pattern or "\x00" in pattern or "//" in pattern:
            raise IgnorePolicyError(
                f".ipriskignore pattern is invalid at line {line_number}"
            )
        parts = pattern.split("/")[1:]
        if any(part in {".", ".."} for part in parts):
            raise IgnorePolicyError(
                f".ipriskignore traversal is invalid at line {line_number}"
            )
        if pattern.endswith("/"):
            pattern += "**"
        rules.append(
            IgnoreRule(
                pattern=pattern,
                expression=re.compile(_glob_expression(pattern.casefold())),
            )
        )
    return tuple(rules)


def is_ignored(logical_path: str, rules: tuple[IgnoreRule, ...]) -> bool:
    if not logical_path.startswith("/") or "\\" in logical_path or "\x00" in logical_path:
        raise IgnorePolicyError("logical path must be canonical and mount-absolute")
    if any(part in {"", ".", ".."} for part in logical_path.split("/")[1:]):
        raise IgnorePolicyError("logical path contains invalid traversal")
    candidate = logical_path.casefold()
    return any(rule.expression.fullmatch(candidate) is not None for rule in rules)


def _glob_expression(pattern: str) -> str:
    expression: list[str] = ["^"]
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
    expression.append("$")
    return "".join(expression)


__all__ = ["IgnorePolicyError", "IgnoreRule", "is_ignored", "parse_ipriskignore"]
