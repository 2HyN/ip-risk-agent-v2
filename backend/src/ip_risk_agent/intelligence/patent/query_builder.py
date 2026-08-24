"""검색 실행.

검색어 하나가 실패해도 나머지는 계속한다. 다만 하나라도 실패하면 후보 목록이
불완전하므로 그 사실을 함께 돌려준다 (Agent 3 Spec 15).

## 0-hit 완화 (확장 전략)

AND 검색은 3단어 질의에서 자주 전멸한다. 확장 전략은 0건 질의의 **뒤 단어를 떼고**
(추출 프롬프트 v3 가 "중요한 단어를 앞에" 를 계약으로 삼는다) 2단어로 딱 한 번
다시 검색한다. 2단어 0건은 그대로 0건이다 — 1단어는 AND 의 뜻이 사라진다.

완화로 얻은 히트는 **원 질의 키 아래** 넣는다. ``matched_queries`` 의 의미와
``query_reach`` 산식이 보존되어야 하기 때문이다. 이때 캐시가 돌려준 객체를
변이하지 않고 ``dataclasses.replace`` 로 새로 만든다 — 완화 질의 문자열 자체가
다른 원 질의로도 존재하면 같은 캐시 객체를 공유하므로, 변이는 캐시 오염이다
(계획 문서 §6-2).

두 원 질의가 같은 완화 질의로 수렴하면 정렬 순서상 첫 질의에만 귀속한다 —
같은 검색 1회가 다중 질의 합의 신호로 부풀지 않게 한다.

## 단계 마감 (확장 전략)

질의 수가 늘면 최악 지연(질의당 타임아웃 × 재시도)이 worker 요청 예산을 뚫는다.
마감을 넘긴 질의는 취소하고 **실패로 기록**한다 — 조용히 줄이는 것이 아니라
coverage 가 PARTIAL 로 낮아진다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace

from ..common.errors import FailureCategory, ProviderFailureError
from .kipris import PROVIDER, PatentSearchHit, PatentSearchProvider


@dataclass
class SearchOutcome:
    """검색 전체의 결과. 성공과 실패를 함께 들고 있다."""

    hits_by_query: dict[str, list[PatentSearchHit]] = field(default_factory=dict)
    failures: list[ProviderFailureError] = field(default_factory=list)
    #: 완화가 일어난 질의: 원 질의 -> 완화 질의. 진단은 개수만 쓴다.
    relaxations: dict[str, str] = field(default_factory=dict)
    #: 완화 검색으로 0건이 1건 이상이 된 질의 수.
    relax_recovered: int = 0

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

    @property
    def zero_hit_queries(self) -> int:
        return sum(1 for hits in self.hits_by_query.values() if not hits)


def _relaxed_query(query: str) -> str | None:
    words = query.split()
    if len(words) < 3:
        return None
    return " ".join(words[:2])


async def run_searches(
    provider: PatentSearchProvider,
    queries: list[str],
    *,
    rows: int = 5,
    relax_zero_hits: bool = False,
    stage_deadline_seconds: float | None = None,
) -> SearchOutcome:
    """검색어들을 동시에 실행한다. 기본 인자는 현행(베이스라인)과 같다."""
    outcome = SearchOutcome()
    if not queries:
        return outcome

    started = time.monotonic()

    def _remaining() -> float | None:
        if stage_deadline_seconds is None:
            return None
        return stage_deadline_seconds - (time.monotonic() - started)

    await _gather_round(
        provider,
        queries,
        rows=rows,
        outcome=outcome,
        deadline=_remaining(),
        assign_to=None,
    )

    if not relax_zero_hits:
        return outcome

    # ── 완화 라운드. 0건 질의를 정렬 순서로 훑어 계획을 먼저 확정한다 —
    # 어느 원 질의가 완화 결과를 가져갈지가 완료 순서에 흔들리면 안 된다.
    originals = set(queries)
    used_targets: set[str] = set()
    relax_plan: dict[str, str] = {}
    for query in sorted(outcome.hits_by_query):
        if outcome.hits_by_query[query]:
            continue
        target = _relaxed_query(query)
        if target is None or target in originals or target in used_targets:
            continue
        used_targets.add(target)
        relax_plan[query] = target

    if not relax_plan:
        return outcome

    relaxed_hits: dict[str, list[PatentSearchHit]] = {}
    await _gather_round(
        provider,
        list(relax_plan.values()),
        rows=rows,
        outcome=outcome,
        deadline=_remaining(),
        assign_to=relaxed_hits,
    )

    for original, target in relax_plan.items():
        hits = relaxed_hits.get(target)
        if hits is None:
            # 완화 검색이 실패했다. 실패는 위에서 이미 기록됐고, 원 질의의
            # 정상 0건 기록은 그대로 남는다.
            continue
        outcome.relaxations[original] = target
        if not hits:
            continue
        outcome.relax_recovered += 1
        # 캐시 객체를 변이하지 않는다 — 원 질의 귀속본을 새로 만든다.
        outcome.hits_by_query[original] = [
            replace(
                hit,
                query=original,
                metadata={**hit.metadata, "relaxed": "true"},
            )
            for hit in hits
        ]
    return outcome


async def _gather_round(
    provider: PatentSearchProvider,
    queries: list[str],
    *,
    rows: int,
    outcome: SearchOutcome,
    deadline: float | None,
    assign_to: dict[str, list[PatentSearchHit]] | None,
) -> None:
    """한 라운드를 실행한다. ``assign_to`` 가 없으면 결과를 outcome 에 직접 싣는다."""

    def _record(query: str, hits: list[PatentSearchHit]) -> None:
        if assign_to is None:
            # 0건도 정상적인 결과다. 실패와 구분해 기록한다.
            outcome.hits_by_query[query] = hits
        else:
            assign_to[query] = hits

    if deadline is not None and deadline <= 0:
        for _ in queries:
            outcome.failures.append(
                ProviderFailureError(
                    PROVIDER,
                    FailureCategory.TIMEOUT,
                    "search stage deadline exceeded",
                )
            )
        return

    if deadline is None:
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
                _record(query, result)
        return

    tasks = {
        query: asyncio.ensure_future(provider.search(query, rows=rows))
        for query in queries
    }
    done, pending = await asyncio.wait(tasks.values(), timeout=deadline)
    for query, task in tasks.items():
        if task in pending:
            task.cancel()
            outcome.failures.append(
                ProviderFailureError(
                    PROVIDER,
                    FailureCategory.TIMEOUT,
                    "search stage deadline exceeded",
                )
            )
            continue
        error = task.exception()
        if error is None:
            _record(query, task.result())
        elif isinstance(error, ProviderFailureError):
            outcome.failures.append(error)
        else:
            raise error
    if pending:
        # 취소가 끝나기를 기다려 이벤트 루프에 잔여 작업을 남기지 않는다.
        await asyncio.gather(*pending, return_exceptions=True)
