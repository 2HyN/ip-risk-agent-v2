"""KIPRIS 응답 캐시의 Firestore 구현.

프로세스 안에만 두면 재분석 때마다 다시 받아온다. 아끼려는 호출이 바로 그것이므로
프로세스 밖에 남겨야 한다.

검색·상세 캐시에 담기는 것은 **공개된 특허 문헌**이지 사용자 원문이 아니다.
근거로 이미 청구항 일부를 저장하고 있고, 이 캐시는 그 출처를 다시 부르지 않기
위한 것이다. 사용자 문서 원문은 어떤 경우에도 들어가지 않는다.

추출 캐시는 다르다. 기술 요소와 검색어는 **사용자 문서에서 파생된 값**이다.
그래서 그 문서가 속한 workspace 를 함께 적어 두고, workspace 삭제 때 지운다
(``gcp/operational_eraser.py`` 의 ``OPERATIONAL_COLLECTIONS``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from ip_risk_agent.intelligence.patent.cache import (
    CachedDocument,
    CachedExtraction,
    CachedSearch,
)
from ip_risk_agent.intelligence.patent.kipris import PatentDocument, PatentSearchHit

SEARCH_COLLECTION = "intelligence_patent_search_cache"
DOCUMENT_COLLECTION = "intelligence_patent_document_cache"
EXTRACTION_COLLECTION = "intelligence_patent_extraction_cache"

_SCHEMA_VERSION = 1


def _document_id(value: str) -> str:
    """검색어가 그대로 문서 ID 가 되지 않게 한다.

    검색어는 사용자 문서에서 파생된 값이다. Firestore 문서 ID 는 콘솔과 로그에
    그대로 드러나므로 해시로 둔다.
    """
    return sha256(value.encode("utf-8")).hexdigest()


class FirestorePatentResponseCache:
    def __init__(self, client) -> None:
        self._client = client

    # ------------------------------------------------------------ 검색

    async def get_search(self, key: str) -> CachedSearch | None:
        data = await self._get(SEARCH_COLLECTION, _document_id(key))
        if data is None:
            return None
        hits = [
            PatentSearchHit(
                application_number=str(item.get("application_number", "")),
                title=str(item.get("title", "")),
                query=str(item.get("query", "")),
                metadata={
                    str(k): str(v) for k, v in (item.get("metadata") or {}).items()
                },
                # 옛 캐시 항목에는 없다 — 빈 문자열이면 BM25 가 제목만 쓴다.
                abstract=str(item.get("abstract", "")),
            )
            for item in data.get("hits") or []
        ]
        return CachedSearch(hits=hits, stored_at=_stored_at(data))

    async def put_search(self, key: str, value: CachedSearch) -> None:
        await self._put(
            SEARCH_COLLECTION,
            _document_id(key),
            {
                "hits": [
                    {
                        "application_number": hit.application_number,
                        "title": hit.title,
                        "query": hit.query,
                        "metadata": dict(hit.metadata),
                        "abstract": hit.abstract,
                    }
                    for hit in value.hits
                ],
                "stored_at": value.stored_at,
            },
        )

    # ------------------------------------------------------------ 상세

    async def get_document(self, application_number: str) -> CachedDocument | None:
        data = await self._get(DOCUMENT_COLLECTION, _document_id(application_number))
        if data is None:
            return None
        document = PatentDocument(
            application_number=str(data.get("application_number", "")),
            title=str(data.get("title", "")),
            abstract=str(data.get("abstract", "")),
            claims=[str(claim) for claim in data.get("claims") or []],
            metadata={
                str(k): str(v) for k, v in (data.get("metadata") or {}).items()
            },
        )
        return CachedDocument(document=document, stored_at=_stored_at(data))

    async def put_document(
        self, application_number: str, value: CachedDocument
    ) -> None:
        document = value.document
        await self._put(
            DOCUMENT_COLLECTION,
            _document_id(application_number),
            {
                "application_number": document.application_number,
                "title": document.title,
                "abstract": document.abstract,
                "claims": list(document.claims),
                "metadata": dict(document.metadata),
                "stored_at": value.stored_at,
            },
        )

    # ------------------------------------------------------------ 추출

    async def get_extraction(self, key: str) -> CachedExtraction | None:
        data = await self._get(EXTRACTION_COLLECTION, _document_id(key))
        if data is None:
            return None
        payload = data.get("payload")
        if not isinstance(payload, dict):
            # 모양이 아니면 캐시를 믿지 않는다. 다시 뽑으면 그만이다.
            return None
        return CachedExtraction(
            payload=payload,
            stored_at=_stored_at(data),
            risk_workspace_id=str(data.get("risk_workspace_id", "")),
        )

    async def put_extraction(self, key: str, value: CachedExtraction) -> None:
        await self._put(
            EXTRACTION_COLLECTION,
            _document_id(key),
            {
                "payload": dict(value.payload),
                "stored_at": value.stored_at,
                # workspace 삭제가 이 문서를 찾을 수 있는 유일한 실마리다.
                # 키는 문서 내용 체크섬이라 그것만으로는 알 수 없다.
                "risk_workspace_id": value.risk_workspace_id,
            },
        )

    # ------------------------------------------------------------ 내부

    async def _get(self, collection: str, document_id: str) -> dict | None:
        snapshot = await self._client.collection(collection).document(document_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if data.get("schema_version") != _SCHEMA_VERSION:
            # 모양이 바뀌었으면 캐시를 믿지 않는다. 다시 받으면 그만이다.
            return None
        return data

    async def _put(self, collection: str, document_id: str, payload: dict) -> None:
        await self._client.collection(collection).document(document_id).set(
            {"schema_version": _SCHEMA_VERSION, **payload}
        )


def _stored_at(data: dict) -> datetime:
    value = data.get("stored_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # 시각을 잃었으면 만료된 것으로 본다. 다시 받는 쪽이 안전하다.
    return datetime.fromtimestamp(0, tz=timezone.utc)


__all__ = [
    "DOCUMENT_COLLECTION",
    "EXTRACTION_COLLECTION",
    "FirestorePatentResponseCache",
    "SEARCH_COLLECTION",
]
