"""GitHub tracking scope — 어떤 경로를 추적할 것인가.

패턴 해석은 :mod:`ip_risk_agent.core.security.ignore_patterns` 가 정한다. 예전에는
여기서 ``fnmatch`` 로 따로 판단해, 같은 ``node_modules`` 가 수단마다 다르게 걸렸다
(§9.1). 거르는 수단이 셋인데 매처가 셋이면 **어느 것도 믿을 수 없다.**

``exclude`` 가 항상 ``include`` 를 이긴다.
"""

from __future__ import annotations

from functools import cached_property

from pydantic import Field

from iprisk_contracts.common import StrictModel

from ip_risk_agent.core.security.ignore_patterns import (
    IgnoreRule,
    compile_pattern,
    is_ignored,
)


class GitHubTrackingScope(StrictModel):
    mount_id: str
    owner: str
    repo: str
    default_branch: str
    tracked_branch: str
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)

    @cached_property
    def _excludes(self) -> tuple[IgnoreRule, ...]:
        return tuple(compile_pattern(item) for item in self.exclude_patterns)

    @cached_property
    def _includes(self) -> tuple[IgnoreRule, ...]:
        return tuple(compile_pattern(item) for item in self.include_patterns)

    def is_tracked(self, path: str) -> bool:
        if is_ignored(path, self._excludes):
            return False
        if not self.include_patterns:
            return True
        return is_ignored(path, self._includes)
