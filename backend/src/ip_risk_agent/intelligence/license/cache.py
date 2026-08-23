"""조항 검색 캐시 (§9.2 · 2-F).

## 왜 라이선스 단위인가

같은 라이선스가 여러 패키지에 반복된다. 실측 저장소에서 MIT 만 다섯 번 나왔다.
패키지마다 검색하면 같은 질의를 다섯 번 보낸다. **라이선스 단위로 캐시하면 그것이
한 번이 된다.**

이 캐시가 §7.6(주기적 재평가)의 선행이다. 주기적으로 도는 조회는 의존성 수에
비례하므로, 캐시가 없으면 그 비용이 주기를 정하지 못하게 만든다.

## 키가 넷인 이유

``(정규화된 표현식, 판정, corpus 버전, 배포형태축 해시)``

* **표현식** — 무엇의 조항을 찾는가.
* **판정** — 질의에 들어간다. ``REVIEW_REQUIRED`` 와 ``POLICY_CONFLICT`` 는 다른
  조항을 찾는다.
* **corpus 버전** — 아래를 보라.
* **배포형태축** — 이것이 빠지면 **SaaS workspace 의 조항 결과가 사내 전용
  workspace 에 그대로 서빙된다.** D7 의 "워크스페이스는 서로 완전히 독립" 이 깨진다.
  축이 질의를 만들기 때문이다 (§5.7 · §5.10).

## corpus 버전을 키에 넣지, 갱신 때 지우지 않는다

같은 결과를 내면서 세 가지가 낫다.

* 지우는 절차가 없으니 **무효화 실패라는 실패 모드가 없다.** 지우기는 반드시
  일부만 지워지는 날이 오고, 그때 남은 항목은 옛 corpus 의 답인데 새 판본의 답처럼
  보인다.
* corpus 를 되돌리면 **옛 캐시가 그대로 살아 있어 롤백이 싸다.**
* 두 판본을 나란히 두고 비교할 수 있다 — §10 의 "이행 차이 수" 를 재는 자리다.

## 무엇을 담는가

**게이트를 통과하기 전의 조각**을 담는다. 주제 일치 판정(``reference_gate``)은 순수
계산이라 아낄 것이 없고, 판정 결과를 담아 두면 게이트를 고쳐도 옛 판단이 계속
서빙된다. 비싼 것은 검색 호출뿐이므로 그것만 담는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Protocol

from .explanation import ReferenceChunk
from .policy import LicensePolicyOutcome


@dataclass(frozen=True, slots=True)
class CachedClauseSearch:
    """한 번의 검색이 돌려준 조각들. 게이트 통과 전이다."""

    chunks: tuple[ReferenceChunk, ...]
    stored_at: datetime


class ClauseSearchCache(Protocol):
    """없으면 캐시 없이 동작한다. 특허 쪽 ``PatentResponseCache`` 와 같은 모양이다."""

    async def get_clause_search(self, key: str) -> CachedClauseSearch | None: ...
    async def put_clause_search(self, key: str, value: CachedClauseSearch) -> None: ...


def clause_cache_key(
    *,
    license_expression: str,
    outcome: LicensePolicyOutcome,
    corpus_version: str | None,
    axes_hash: str,
) -> str:
    """네 조각을 하나의 키로.

    조각을 이름과 함께 적고 해시한다. 이어 붙이기만 하면 한 조각의 끝과 다음
    조각의 시작이 섞여 **다른 입력이 같은 키**가 될 수 있다.

    ``corpus_version`` 이 ``None`` 인 경우도 키가 된다 — 판본을 모르는 검색과 아는
    검색은 다른 것이고, 모르는 쪽을 아는 쪽과 같은 칸에 넣으면 판본이 붙은 뒤에도
    옛 답이 나온다.
    """
    material = "|".join(
        (
            f"expression={license_expression}",
            f"outcome={outcome.value}",
            f"corpus={corpus_version or 'unknown'}",
            f"axes={axes_hash}",
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


class InMemoryClauseSearchCache:
    """한 프로세스 안에서만 사는 캐시. 시험과 개발용이다."""

    def __init__(self) -> None:
        self._entries: dict[str, CachedClauseSearch] = {}
        self.hits = 0
        self.misses = 0

    async def get_clause_search(self, key: str) -> CachedClauseSearch | None:
        found = self._entries.get(key)
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    async def put_clause_search(self, key: str, value: CachedClauseSearch) -> None:
        self._entries[key] = value


__all__ = [
    "CachedClauseSearch",
    "ClauseSearchCache",
    "InMemoryClauseSearchCache",
    "clause_cache_key",
]
