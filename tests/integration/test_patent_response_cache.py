"""KIPRIS 응답 캐시의 Firestore 구현.

이 파일이 없어서 운영이 멈췄다. ``PatentResponseCache`` Protocol 에 추출 캐시가
추가되고 메모리 구현(시험용)에는 붙었는데 **Firestore 구현에만 빠져 있었다.**
Protocol 은 실행 중에 검사되지 않으므로 모든 시험이 통과했고, 배포에서 분석이
``AttributeError`` 로 즉시 죽었다 — 화면에는 뜻을 알 수 없는
``INTERNAL:UNEXPECTED_PIPELINE_FAILURE`` 만 남았다.

그래서 여기서 **구현이 계약을 만족하는지**부터 확인한다. 다음에 Protocol 에
메서드가 늘어도 같은 방식으로 멈추지 않는다.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from ip_risk_agent.gcp.operational_eraser import OPERATIONAL_COLLECTIONS
from ip_risk_agent.gcp.patent_cache import (
    EXTRACTION_COLLECTION,
    FirestorePatentResponseCache,
)
from ip_risk_agent.intelligence.patent.cache import (
    CachedDocument,
    CachedExtraction,
    CachedSearch,
    PatentResponseCache,
)
from ip_risk_agent.intelligence.patent.kipris import PatentDocument, PatentSearchHit

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


class _FakeDocument:
    def __init__(self, store: dict, path: tuple[str, str]) -> None:
        self._store = store
        self._path = path

    async def get(self) -> "_FakeDocument":
        return self

    @property
    def exists(self) -> bool:
        return self._path in self._store

    def to_dict(self) -> dict | None:
        data = self._store.get(self._path)
        return None if data is None else dict(data)

    async def set(self, payload: dict) -> None:
        self._store[self._path] = dict(payload)


class _FakeCollection:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self._name = name

    def document(self, document_id: str) -> _FakeDocument:
        return _FakeDocument(self._store, (self._name, document_id))


class _FakeClient:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], dict] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.store, name)


def _cache() -> tuple[FirestorePatentResponseCache, _FakeClient]:
    client = _FakeClient()
    return FirestorePatentResponseCache(client), client


def test_the_production_cache_implements_every_method_the_contract_declares() -> None:
    """이것이 없어서 운영이 멈췄다.

    Protocol 은 실행 중에 검사되지 않는다. 메서드 하나가 빠져도 시험은 통과하고
    배포에서만 ``AttributeError`` 가 난다.
    """
    declared = [
        name
        for name in dir(PatentResponseCache)
        if not name.startswith("_") and callable(getattr(PatentResponseCache, name))
    ]
    assert declared, "계약에 메서드가 하나도 없다면 이 시험은 아무것도 지키지 않는다"
    for name in declared:
        method = getattr(FirestorePatentResponseCache, name, None)
        assert method is not None, f"운영 구현에 {name} 이 없다"
        assert inspect.iscoroutinefunction(method), f"{name} 은 await 되는 자리에 쓰인다"


def test_an_extraction_survives_a_round_trip_with_its_workspace() -> None:
    async def scenario() -> None:
        cache, _client = _cache()
        stored = CachedExtraction(
            payload={"is_technical": True, "search_queries": ["음성 특징 추출"]},
            stored_at=NOW,
            risk_workspace_id="workspace-abc",
        )
        await cache.put_extraction("key-1", stored)
        loaded = await cache.get_extraction("key-1")
        assert loaded is not None
        assert loaded.payload == stored.payload
        assert loaded.stored_at == NOW
        # workspace 를 잃으면 삭제가 이 문서를 찾지 못한다.
        assert loaded.risk_workspace_id == "workspace-abc"

    asyncio.run(scenario())


def test_a_missing_extraction_is_a_miss_not_an_error() -> None:
    async def scenario() -> None:
        cache, _client = _cache()
        assert await cache.get_extraction("nothing here") is None

    asyncio.run(scenario())


def test_the_search_query_never_becomes_the_document_id() -> None:
    """검색어는 사용자 문서에서 나온 값이다. 문서 ID 는 콘솔과 로그에 드러난다."""

    async def scenario() -> None:
        cache, client = _cache()
        await cache.put_extraction(
            "patent_extract_v2:sha256:secret-document",
            CachedExtraction(payload={}, stored_at=NOW, risk_workspace_id="w"),
        )
        ids = [document_id for _collection, document_id in client.store]
        assert ids
        assert all("secret-document" not in item for item in ids)

    asyncio.run(scenario())


def test_a_document_from_an_older_shape_is_ignored() -> None:
    """모양이 바뀌었으면 다시 뽑으면 그만이다. 잘못 읽는 것보다 낫다."""

    async def scenario() -> None:
        cache, client = _cache()
        await cache.put_extraction(
            "key-1", CachedExtraction(payload={"a": 1}, stored_at=NOW, risk_workspace_id="w")
        )
        (path,) = list(client.store)
        client.store[path]["schema_version"] = 99
        assert await cache.get_extraction("key-1") is None

    asyncio.run(scenario())


def test_the_extraction_cache_is_erased_with_its_workspace() -> None:
    """추출 캐시에는 문서에서 뽑은 기술 요소와 검색어가 들어 있다.

    원문은 아니지만 원문에서 나온 값이다. Workspace 삭제는 전체 말소다.
    """
    assert EXTRACTION_COLLECTION in OPERATIONAL_COLLECTIONS


@pytest.mark.parametrize(
    "collection",
    ("intelligence_patent_search_cache", "intelligence_patent_document_cache"),
)
def test_the_public_patent_caches_are_not_erased_with_a_workspace(collection: str) -> None:
    """공개 특허 문헌이다. 지우면 다음 workspace 가 KIPRIS 한도를 다시 쓴다."""
    assert collection not in OPERATIONAL_COLLECTIONS


def test_search_and_document_entries_still_round_trip() -> None:
    """추출 캐시를 붙이면서 기존 두 캐시를 깨뜨리지 않았는지 본다."""

    async def scenario() -> None:
        cache, _client = _cache()
        hit = PatentSearchHit(
            application_number="1020230001234",
            title="음성 특징 기반 탐지",
            query="음성 특징",
            metadata={"position": "1"},
        )
        await cache.put_search("q", CachedSearch(hits=[hit], stored_at=NOW))
        loaded_search = await cache.get_search("q")
        assert loaded_search is not None
        assert [item.application_number for item in loaded_search.hits] == [
            "1020230001234"
        ]

        document = PatentDocument(
            application_number="1020230001234",
            title="음성 특징 기반 탐지",
            abstract="요약",
            claims=["청구항 1"],
            metadata={},
        )
        await cache.put_document(
            "1020230001234",
            CachedDocument(document=document, stored_at=NOW - timedelta(days=1)),
        )
        loaded_document = await cache.get_document("1020230001234")
        assert loaded_document is not None
        assert loaded_document.document.claims == ["청구항 1"]

    asyncio.run(scenario())
