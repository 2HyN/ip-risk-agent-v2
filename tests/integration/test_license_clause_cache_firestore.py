"""조항 캐시의 Firestore 구현 (§9.2 · 2-F).

프로세스 안에만 두면 재분석 때마다 다시 검색한다 — **아끼려는 호출이 바로 그것이다.**
주기적 재평가(§7.6)는 의존성 수에 비례해 도는데, 그 조회가 매번 실호출이면 캐시가
있으나 없으나 같다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ip_risk_agent.gcp.license_clause_cache import (
    CLAUSE_COLLECTION,
    FirestoreClauseSearchCache,
)
from ip_risk_agent.gcp.operational_eraser import OPERATIONAL_COLLECTIONS
from ip_risk_agent.intelligence.license.cache import (
    CachedClauseSearch,
    ClauseSearchCache,
    clause_cache_key,
)
from ip_risk_agent.intelligence.license.explanation import ReferenceChunk
from ip_risk_agent.intelligence.license.policy import LicensePolicyOutcome

NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)


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


CHUNK = ReferenceChunk(
    source_id="agpl-3.0-obligations",
    chunk_id="c1",
    text="네트워크를 통해 상호작용하게 하는 경우 …",
    canonical_reference="AGPL-3.0 §13",
    metadata={"covers": "AGPL-3.0-only"},
)
KEY = clause_cache_key(
    license_expression="AGPL-3.0-only",
    outcome=LicensePolicyOutcome.POLICY_CONFLICT,
    corpus_version="2026-08-23.4",
    axes_hash="abc",
)


def _cache() -> tuple[FirestoreClauseSearchCache, _FakeClient]:
    client = _FakeClient()
    return FirestoreClauseSearchCache(client), client


def test_the_production_cache_implements_every_method_the_contract_declares() -> None:
    """구현이 프로토콜과 어긋나면 운영에서만 드러난다."""
    for name in ClauseSearchCache.__protocol_attrs__:  # type: ignore[attr-defined]
        assert hasattr(FirestoreClauseSearchCache, name), name


def test_a_stored_search_comes_back_the_same() -> None:
    cache, _ = _cache()

    async def scenario():
        await cache.put_clause_search(
            KEY, CachedClauseSearch(chunks=(CHUNK,), stored_at=NOW)
        )
        return await cache.get_clause_search(KEY)

    found = asyncio.run(scenario())
    assert found is not None
    assert found.chunks == (CHUNK,)
    assert found.stored_at == NOW


def test_a_missing_key_is_a_miss_not_an_error() -> None:
    cache, _ = _cache()
    assert asyncio.run(cache.get_clause_search(KEY)) is None


def test_a_document_from_an_older_shape_is_not_trusted() -> None:
    """모양이 바뀌었으면 캐시를 믿지 않는다. 다시 검색하면 그만이다."""
    cache, client = _cache()

    async def scenario():
        await cache.put_clause_search(
            KEY, CachedClauseSearch(chunks=(CHUNK,), stored_at=NOW)
        )
        (path,) = list(client.store)
        client.store[path]["schema_version"] = 999
        return await cache.get_clause_search(KEY)

    assert asyncio.run(scenario()) is None


def test_the_key_is_not_the_document_id() -> None:
    """문서 ID 는 콘솔과 로그에 그대로 드러난다."""
    cache, client = _cache()
    asyncio.run(
        cache.put_clause_search(KEY, CachedClauseSearch(chunks=(), stored_at=NOW))
    )
    (collection, document_id), = list(client.store)
    assert collection == CLAUSE_COLLECTION
    assert document_id != KEY


def test_the_clause_cache_is_not_erased_with_a_workspace() -> None:
    """담기는 것은 우리가 corpus 에 올린 **공개 SPDX 전문**이다.

    키도 라이선스 표현식 · 판정 · corpus 판본 · 배포형태 해시로만 만들어져 사용자
    소스에서 온 값이 없다. 특허 **추출** 캐시와 다른 점이 이것이고, 그래서 workspace
    삭제 때 지울 것이 없다 — 라이선스 조항은 그 workspace 의 것이 아니다.

    같은 설정을 쓰는 workspace 끼리 나눠 쓰는 것이 이 캐시의 목적이다 (§9.2).
    """
    assert CLAUSE_COLLECTION not in OPERATIONAL_COLLECTIONS
