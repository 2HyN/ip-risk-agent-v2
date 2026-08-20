"""Agent2 Spec 17/18번: GitHub tracking scope (include/exclude glob 패턴).

fnmatch는 '*'가 경로 구분자('/')도 그냥 매칭해서, 'src/**' 같은 패턴이
명세 예시 그대로 동작한다 (실제로 검증함). exclude가 항상 include를 이긴다.
"""

from __future__ import annotations

import fnmatch

from pydantic import Field

from iprisk_contracts.common import StrictModel


class GitHubTrackingScope(StrictModel):
    mount_id: str
    owner: str
    repo: str
    default_branch: str
    tracked_branch: str
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)

    def is_tracked(self, path: str) -> bool:
        if any(fnmatch.fnmatch(path, pattern) for pattern in self.exclude_patterns):
            return False
        if not self.include_patterns:
            return True
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.include_patterns)
