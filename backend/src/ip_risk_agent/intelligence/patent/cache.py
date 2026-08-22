"""KIPRIS 응답 캐시.

무료 등급의 호출 한도는 **월 1,000 회**이고 매월 1 일에 초기화된다. 분석 한 건이
검색 5 회 + 상세조회 6 회 정도를 쓰므로 대략 11 회다. 문서 20 건을 일괄 재분석하면
220 회, 즉 한 달치의 5 분의 1 을 한 번에 쓴다. 실제로 하루 만에 한도를 소진했다.

그런데 그 호출의 대부분은 **같은 것을 다시 받아오는 것**이다.

* 등록·공개된 특허의 서지·초록·청구항은 바뀌지 않는다. 같은 출원번호를 재분석마다
  다시 받을 이유가 없다
* 같은 검색어의 결과는 새 공보가 나올 때만 바뀐다. 며칠 단위로는 사실상 같다

그래서 상세조회는 길게, 검색은 짧게 캐시한다. 이것은 성능 최적화가 아니라
**재검증을 가능하게 만드는 것**이다 — 캐시가 없으면 같은 문서를 두 번 검증하는
데도 한도를 쓴다.

캐시는 provider 를 감싸는 것으로 붙인다. Analyzer 는 ``PatentSearchProvider`` 만
알고 있으므로 바뀌지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .kipris import PatentDocument, PatentSearchHit, PatentSearchProvider

#: 등록된 특허의 서지는 바뀌지 않는다. 길게 잡되 영원히 두지는 않는다 —
#: 정정공고나 우리 파서 변경이 반영될 길은 남겨 둔다.
DOCUMENT_TTL = timedelta(days=90)

#: 검색은 새 공보가 나오면 달라진다. 검토 도구의 주기로는 일주일이면 충분하다.
SEARCH_TTL = timedelta(days=7)

#: 문서가 그대로면 검색어도 그대로여야 한다.
#:
#: 추출은 모델이 하므로 같은 문서라도 실행마다 검색어가 달라진다. 그러면 후보가
#: 달라지고, **바뀐 것이 없는데 Risk 가 새로 생기고 이전 것이 해소된다.** 운영에서
#: 실제로 그랬다 — 같은 문서를 재검사했더니 특허 2 건이 새로 잡히고 2 건이
#: RESOLVED 가 됐다.
#:
#: 그래서 문서 내용(analysis_input_checksum)이 같으면 검색어를 재사용한다.
#: 내용이 바뀌면 체크섬이 바뀌므로 자연히 다시 뽑는다 — 그때는 검색어가 달라지는
#: 것이 옳다.
EXTRACTION_TTL = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class CachedSearch:
    hits: list[PatentSearchHit]
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class CachedExtraction:
    payload: dict
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class CachedDocument:
    document: PatentDocument
    stored_at: datetime


class PatentResponseCache(Protocol):
    """provider 응답 저장소. 없으면 캐시 없이 동작한다."""

    async def get_search(self, key: str) -> CachedSearch | None: ...
    async def put_search(self, key: str, value: CachedSearch) -> None: ...
    async def get_document(self, application_number: str) -> CachedDocument | None: ...
    async def put_document(
        self, application_number: str, value: CachedDocument
    ) -> None: ...
    async def get_extraction(self, key: str) -> CachedExtraction | None: ...
    async def put_extraction(self, key: str, value: CachedExtraction) -> None: ...


class InMemoryPatentResponseCache:
    """한 프로세스 안에서만 사는 캐시. 시험과 개발용이다."""

    def __init__(self) -> None:
        self._searches: dict[str, CachedSearch] = {}
        self._documents: dict[str, CachedDocument] = {}
        self._extractions: dict[str, CachedExtraction] = {}

    async def get_search(self, key: str) -> CachedSearch | None:
        return self._searches.get(key)

    async def put_search(self, key: str, value: CachedSearch) -> None:
        self._searches[key] = value

    async def get_document(self, application_number: str) -> CachedDocument | None:
        return self._documents.get(application_number)

    async def put_document(
        self, application_number: str, value: CachedDocument
    ) -> None:
        self._documents[application_number] = value

    async def get_extraction(self, key: str) -> CachedExtraction | None:
        return self._extractions.get(key)

    async def put_extraction(self, key: str, value: CachedExtraction) -> None:
        self._extractions[key] = value


def extraction_cache_key(analysis_input_checksum: str, prompt_version: str) -> str:
    """문서 내용과 프롬프트가 함께 검색어를 정한다. 둘 다 키에 넣는다.

    프롬프트를 고치면 검색어가 달라지는 것이 옳으므로 캐시가 자연히 무효화된다.
    """
    return f"{prompt_version}:{analysis_input_checksum}"


def search_cache_key(query: str, rows: int) -> str:
    """검색어와 요청 건수가 함께 결과를 정한다. 둘 다 키에 넣는다."""
    return f"{rows}:{query.strip()}"


class CachingPatentSearchProvider:
    """``PatentSearchProvider`` 를 감싸 같은 응답을 다시 받지 않게 한다.

    캐시 실패는 분석을 막지 않는다. 저장소가 응답하지 않아도 provider 를 직접
    부르면 되고, 그것이 원래 동작이다. 반대로 캐시 때문에 분석이 실패하면 아끼려던
    호출을 오히려 더 쓰게 된다.
    """

    def __init__(
        self,
        inner: PatentSearchProvider,
        cache: PatentResponseCache,
        *,
        clock=lambda: datetime.now(timezone.utc),
        document_ttl: timedelta = DOCUMENT_TTL,
        search_ttl: timedelta = SEARCH_TTL,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._clock = clock
        self._document_ttl = document_ttl
        self._search_ttl = search_ttl

    async def search(self, query: str, *, rows: int = 5) -> list[PatentSearchHit]:
        key = search_cache_key(query, rows)
        cached = await self._safe(self._cache.get_search(key))
        now = self._clock()
        if cached is not None and now - cached.stored_at < self._search_ttl:
            return list(cached.hits)
        hits = await self._inner.search(query, rows=rows)
        await self._safe(self._cache.put_search(key, CachedSearch(list(hits), now)))
        return hits

    async def fetch_detail(self, application_number: str) -> PatentDocument:
        cached = await self._safe(self._cache.get_document(application_number))
        now = self._clock()
        if cached is not None and now - cached.stored_at < self._document_ttl:
            return cached.document
        document = await self._inner.fetch_detail(application_number)
        await self._safe(
            self._cache.put_document(
                application_number, CachedDocument(document, now)
            )
        )
        return document

    async def aclose(self) -> None:
        """감싼 provider 의 자원을 닫는다. 감쌌다고 수명 관리가 사라지지 않는다."""
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()

    @staticmethod
    async def _safe(awaitable):
        """캐시 오류는 삼킨다. 캐시는 있으면 좋은 것이지 정확성의 일부가 아니다."""
        try:
            return await awaitable
        except Exception:  # noqa: BLE001 - 캐시 실패는 분석을 막지 않는다
            return None


__all__ = [
    "CachedDocument",
    "CachedExtraction",
    "CachedSearch",
    "EXTRACTION_TTL",
    "extraction_cache_key",
    "CachingPatentSearchProvider",
    "DOCUMENT_TTL",
    "InMemoryPatentResponseCache",
    "PatentResponseCache",
    "SEARCH_TTL",
    "search_cache_key",
]
