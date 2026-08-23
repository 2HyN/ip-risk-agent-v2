"""조항 검색 캐시의 Firestore 구현 (§9.2 · 2-F).

프로세스 안에만 두면 재분석 때마다 다시 검색한다. **아끼려는 호출이 바로 그것이다.**
주기적 재평가(§7.6 · 결함 24)는 의존성 수에 비례해 도는데, 그 조회가 매번 실호출이면
캐시가 있으나 없으나 같다.

## 사용자 원문이 들어가지 않는다

담기는 것은 **SPDX 라이선스 전문**이다 — 우리가 corpus 에 올린 공개 문서이고, 이미
근거로 저장하고 있는 그 조각이다. 키도 라이선스 표현식·판정·corpus 판본·배포형태
해시로만 만들어져 사용자 소스에서 온 값이 없다.

그래서 특허 쪽 **추출 캐시와 달리** workspace 를 적지 않고, workspace 삭제 때 지우지
않는다. 지울 것이 없다 — 라이선스 조항은 그 workspace 의 것이 아니다.

배포형태 해시는 workspace 설정에서 나오지만 **해시라 되돌릴 수 없고**, 같은 설정을 쓰는
workspace 끼리 캐시를 나눠 쓰는 것이 이 캐시의 목적이다 (§9.2).

## 지우지 않는다

corpus 판본이 키에 들어 있으므로 (§9.2) 갱신 때 무효화하지 않는다. 옛 판본의 항목은
아무도 찾지 않는 채로 남는다. 그것이 롤백을 싸게 만드는 바로 그 성질이다.

TTL 은 두지 않는다. corpus 판본이 고정된 동안 답이 달라질 이유가 없고, TTL 이 있으면
"만료돼서 다시 물었더니 다른 답" 이 판정 변화로 보인다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from ip_risk_agent.intelligence.license.cache import CachedClauseSearch
from ip_risk_agent.intelligence.license.explanation import ReferenceChunk

CLAUSE_COLLECTION = "intelligence_license_clause_cache"

_SCHEMA_VERSION = 1


def _document_id(value: str) -> str:
    """키를 그대로 문서 ID 로 쓰지 않는다.

    ``clause_cache_key`` 가 이미 해시를 돌려주지만, 부르는 쪽이 바뀌어도 ID 모양이
    유지되도록 여기서 한 번 더 고정한다. Firestore 문서 ID 는 콘솔과 로그에 그대로
    드러난다.
    """
    return sha256(value.encode("utf-8")).hexdigest()


class FirestoreClauseSearchCache:
    def __init__(self, client) -> None:
        self._client = client

    async def get_clause_search(self, key: str) -> CachedClauseSearch | None:
        snapshot = (
            await self._client.collection(CLAUSE_COLLECTION)
            .document(_document_id(key))
            .get()
        )
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        if data.get("schema_version") != _SCHEMA_VERSION:
            # 모양이 바뀌었으면 캐시를 믿지 않는다. 다시 검색하면 그만이다.
            return None
        raw = data.get("chunks")
        if not isinstance(raw, list):
            return None
        chunks = tuple(
            ReferenceChunk(
                source_id=str(item.get("source_id", "")),
                chunk_id=str(item.get("chunk_id", "")),
                text=str(item.get("text", "")),
                canonical_reference=str(item.get("canonical_reference", "")),
                metadata={
                    str(k): str(v) for k, v in (item.get("metadata") or {}).items()
                },
            )
            for item in raw
            if isinstance(item, dict)
        )
        return CachedClauseSearch(chunks=chunks, stored_at=_stored_at(data))

    async def put_clause_search(self, key: str, value: CachedClauseSearch) -> None:
        await self._client.collection(CLAUSE_COLLECTION).document(
            _document_id(key)
        ).set(
            {
                "schema_version": _SCHEMA_VERSION,
                "chunks": [
                    {
                        "source_id": chunk.source_id,
                        "chunk_id": chunk.chunk_id,
                        "text": chunk.text,
                        "canonical_reference": chunk.canonical_reference,
                        "metadata": dict(chunk.metadata),
                    }
                    for chunk in value.chunks
                ],
                "stored_at": value.stored_at,
            }
        )


def _stored_at(data: dict) -> datetime:
    value = data.get("stored_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # 시각을 잃었어도 답은 유효하다 — corpus 판본이 키에 있기 때문이다. 다만 언제
    # 담겼는지는 모르는 것으로 둔다.
    return datetime.fromtimestamp(0, tz=timezone.utc)


__all__ = ["CLAUSE_COLLECTION", "FirestoreClauseSearchCache"]
