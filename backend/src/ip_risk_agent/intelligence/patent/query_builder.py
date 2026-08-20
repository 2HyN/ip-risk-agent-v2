"""검색 실행.

검색어 하나가 실패해도 나머지는 계속한다. 다만 하나라도 실패하면 후보 목록이
불완전하므로 그 사실을 함께 돌려준다 (Agent 3 Spec 15).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..common.errors import ProviderFailureError
from .kipris import PatentSearchHit, PatentSearchProvider


@dataclass
class SearchOutcome:
    """검색 전체의 결과. 성공과 실패를 함께 들고 있다."""

    hits_by_query: dict[str, list[PatentSearchHit]] = field(default_factory=dict)
    failures: list[ProviderFailureError] = field(default_factory=list)

    @property
    def executed_queries(self) -> int:
        return len(self.hits_by_query)

    @property
    def is_complete(self) -> bool:
        """모든 검색어가 성공했는가. 하나라도 실패하면 coverage 를 낮춘다."""
        return not self.failures

    @property
    def total_hits(self) -> int:
        return sum(len(hits) for hits in self.hits_by_query.values())


async def run_searches(
    provider: PatentSearchProvider,
    queries: list[str],
    *,
    rows: int = 5,
) -> SearchOutcome:
    """검색어들을 동시에 실행한다."""
    outcome = SearchOutcome()
    if not queries:
        return outcome

    results = await asyncio.gather(
        *(provider.search(query, rows=rows) for query in queries),
        return_exceptions=True,
    )
    for query, result in zip(queries, results, strict=True):
        if isinstance(result, ProviderFailureError):
            outcome.failures.append(result)
        elif isinstance(result, BaseException):
            raise result
        else:
            # 0건도 정상적인 결과다. 실패와 구분해 기록한다.
            outcome.hits_by_query[query] = result
    return outcome
