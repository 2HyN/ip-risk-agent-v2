"""후보 정규화·중복 제거·순위.

같은 특허가 여러 검색어에서 나오는 것은 우연이 아니라 신호다. 여러 각도에서
걸렸다는 뜻이므로 앞에 둔다 (Agent 3 Spec 16).

순위는 완전히 결정론적이어야 한다. 실행할 때마다 순서가 달라지면 상위 N건만
판정하는 구조에서 결과가 흔들린다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .kipris import PatentSearchHit

# 판정 비용이 후보 수에 비례한다. 상한을 둔다 (Agent 3 Spec 16).
DEFAULT_CANDIDATE_CAP = 6

#: RRF 표준 상수. 바꾸면 순위의 뜻이 달라지므로 버전과 함께 고정한다.
RRF_K = 60
RANK_VERSION_RRF = "patent_rank_rrf_v1"

#: 완화 검색으로 회수된 히트는 원 질의의 직접 결과보다 가볍게 센다.
_RELAXED_WEIGHT = 0.7

_IPC_SUBCLASS = re.compile(r"([A-H]\d{2}[A-Z])")


@dataclass
class RankedCandidate:
    """중복이 합쳐진 후보 하나."""

    application_number: str
    title: str
    matched_queries: list[str] = field(default_factory=list)
    best_position: int = 0
    metadata: dict[str, str] = field(default_factory=dict)
    #: RRF 전략에서만 채워진다. 기본값이라 기존 생성부는 그대로다.
    rrf_score: float = 0.0
    ipc_consistent: bool = False

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


def _ipc_subclass(raw: str) -> str:
    """IPC 표기에서 서브클래스(예: ``G10L``)만 뽑는다. 못 읽으면 빈 문자열."""
    match = _IPC_SUBCLASS.search((raw or "").upper().replace(" ", ""))
    return match.group(1) if match else ""


def rank_candidates_rrf(
    hits_by_query: dict[str, list[PatentSearchHit]],
    *,
    cap: int = DEFAULT_CANDIDATE_CAP,
    k: int = RRF_K,
    ipc_signal: bool = True,
) -> list[RankedCandidate]:
    """RRF(Reciprocal Rank Fusion) 병합. 확장 전략 전용 — 기존 함수는 그대로다.

    풀이 커지면(질의 12 × rows 30) 현행 정렬의 1차 키(질의 적중 수)는 대부분 1로
    동률이고, 동률은 KIPRIS 내부 순서로 갈린다. RRF 는 질의별 순위 전부를 연속
    점수로 합쳐 그 동률 티어 안을 가른다. **단일 질의 적중 후보끼리는 현행과 같은
    순서를 낸다** — 이 함수의 가치는 단독 개선이 아니라 완화·IPC·(장래) 임베딩
    채널을 같은 틀로 융합할 자리다 (계획 문서 §6-10).

    IPC 는 순위 신호이지 제외 필터가 아니다. 다중 질의 히트 전체의 지배
    서브클래스와 일치하는 후보를 동률에서 앞세울 뿐, 불일치를 이유로 빼지
    않는다 — 필터로 뺀 후보는 "본 적 없음"이지 "낮음"이 아니다 (설계 노트 §4.1).

    순수 산술 + 완전한 동점 사슬(rrf → ipc → 적중 수 → 위치 → 출원번호)이라
    같은 입력이면 같은 순서다.
    """
    merged: dict[str, RankedCandidate] = {}
    scores: dict[str, float] = {}

    for query in sorted(hits_by_query):
        for position, hit in enumerate(hits_by_query[query]):
            weight = (
                _RELAXED_WEIGHT if hit.metadata.get("relaxed") == "true" else 1.0
            )
            scores[hit.application_number] = scores.get(
                hit.application_number, 0.0
            ) + weight / (k + position + 1)

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
            if not existing.title and hit.title:
                existing.title = hit.title

    if ipc_signal:
        profile: Counter[str] = Counter()
        for query in sorted(hits_by_query):
            for hit in hits_by_query[query]:
                subclass = _ipc_subclass(hit.metadata.get("ipc", ""))
                if subclass:
                    profile[subclass] += 1
        # Counter.most_common 은 동률 순서가 비결정적이다. 정렬로 고정한다.
        # "일관성"은 반복을 뜻한다 — 한 번만 나타난 서브클래스는 합의 신호가
        # 아니므로 지배 집합에 넣지 않는다. 상위 3개까지만 본다.
        dominant = {
            subclass
            for subclass, count in sorted(
                profile.items(), key=lambda item: (-item[1], item[0])
            )[:3]
            if count >= 2
        }
        for candidate in merged.values():
            candidate.ipc_consistent = (
                _ipc_subclass(candidate.metadata.get("ipc", "")) in dominant
            )

    for candidate in merged.values():
        # 부동소수 누적 오차가 동점 판정을 흔들지 않게 자리수를 고정한다.
        candidate.rrf_score = round(scores[candidate.application_number], 9)

    ordered = sorted(
        merged.values(),
        key=lambda c: (
            -c.rrf_score,
            -int(c.ipc_consistent),
            -c.query_hits,
            c.best_position,
            c.application_number,
        ),
    )
    return ordered[:cap]
