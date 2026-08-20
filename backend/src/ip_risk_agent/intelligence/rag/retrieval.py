"""참조 지식 검색.

Analyzer 는 RAG Engine SDK 를 모른다. :class:`ReferenceRetriever` 규약만 안다
(Agent 3 Spec 33). 그래서 관리형 서비스든 로컬 색인이든 갈아끼울 수 있다.
"""

from __future__ import annotations

from ..common.errors import FailureCategory, ProviderFailureError
from ..license.explanation import ReferenceChunk

PROVIDER = "RAG_ENGINE"


class InMemoryReferenceRetriever:
    """테스트와 오프라인 개발용.

    실제 검색기를 흉내 내되 순위는 단순 어휘 겹침으로 계산한다. 결과 형태가
    같으므로 Analyzer 쪽 코드는 그대로 둘 수 있다.
    """

    def __init__(
        self,
        chunks: list[ReferenceChunk],
        corpus_version: str,
        *,
        available: bool = True,
    ) -> None:
        self._chunks = list(chunks)
        self._corpus_version = corpus_version
        self._available = available

    @property
    def corpus_version(self) -> str:
        return self._corpus_version

    def set_available(self, available: bool) -> None:
        """장애 상황을 재현할 때 쓴다."""
        self._available = available

    async def retrieve(
        self, query: str, *, filters: dict[str, str] | None = None, top_k: int = 3
    ) -> list[ReferenceChunk]:
        if not self._available:
            raise ProviderFailureError(
                PROVIDER, FailureCategory.UNAVAILABLE, "corpus is not reachable"
            )

        selected = self._chunks
        if filters:
            selected = [
                chunk
                for chunk in selected
                if all(chunk.metadata.get(key) == value for key, value in filters.items())
            ]

        terms = {token for token in query.lower().split() if len(token) > 1}

        def score(chunk: ReferenceChunk) -> tuple[int, str]:
            body = f"{chunk.source_id} {chunk.chunk_id} {chunk.text}".lower()
            # 동점일 때 순서가 흔들리지 않도록 chunk_id 로 묶어 정렬한다.
            return (-sum(term in body for term in terms), chunk.chunk_id)

        return sorted(selected, key=score)[:top_k]
