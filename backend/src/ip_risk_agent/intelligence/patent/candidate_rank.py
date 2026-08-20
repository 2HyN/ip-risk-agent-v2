"""후보 정규화·중복 제거·순위.

같은 특허가 여러 검색어에서 나오는 것은 우연이 아니라 신호다. 여러 각도에서
걸렸다는 뜻이므로 앞에 둔다 (Agent 3 Spec 16).

순위는 완전히 결정론적이어야 한다. 실행할 때마다 순서가 달라지면 상위 N건만
판정하는 구조에서 결과가 흔들린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kipris import PatentSearchHit

# 판정 비용이 후보 수에 비례한다. 상한을 둔다 (Agent 3 Spec 16).
DEFAULT_CANDIDATE_CAP = 6


@dataclass
class RankedCandidate:
    """중복이 합쳐진 후보 하나."""

    application_number: str
    title: str
    matched_queries: list[str] = field(default_factory=list)
    best_position: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def query_hits(self) -> int:
        return len(self.matched_queries)


def rank_candidates(
    hits_by_query: dict[str, list[PatentSearchHit]],
    *,
    cap: int = DEFAULT_CANDIDATE_CAP,
) -> list[RankedCandidate]:
    """검색 결과를 합쳐 순위를 매긴다.

    정렬 기준은 세 단계다.

    1. 여러 검색어에 걸린 것이 앞
    2. 검색 결과에서 더 위에 있던 것이 앞
    3. 출원번호 오름차순 — 동점일 때 순서를 고정하기 위한 것이다
    """
    merged: dict[str, RankedCandidate] = {}

    # 검색어 순서를 고정해 병합 결과가 흔들리지 않게 한다.
    for query in sorted(hits_by_query):
        for position, hit in enumerate(hits_by_query[query]):
            existing = merged.get(hit.application_number)
            if existing is None:
                merged[hit.application_number] = RankedCandidate(
                    application_number=hit.application_number,
                    title=hit.title,
                    matched_queries=[query],
                    best_position=position,
                    metadata=dict(hit.metadata),
                )
                continue

            if query not in existing.matched_queries:
                existing.matched_queries.append(query)
            existing.best_position = min(existing.best_position, position)
            # 제목이 비어 오는 응답이 있다. 채워진 값을 우선한다.
            if not existing.title and hit.title:
                existing.title = hit.title

    ordered = sorted(
        merged.values(),
        key=lambda c: (-c.query_hits, c.best_position, c.application_number),
    )
    return ordered[:cap]
