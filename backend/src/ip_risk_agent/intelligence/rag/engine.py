"""Google Cloud RAG Engine 연동.

Application Plane 은 서울, RAG Engine 은 외부 GA region 에 둔다 (Blueprint 20).
그래서 region 을 하드코딩하지 않고 설정으로 받는다 (Agent 3 Spec 32).

SDK 는 선택 의존성이다. 없으면 생성 시점에 알리고, 개발과 테스트는
:class:`~.retrieval.InMemoryReferenceRetriever` 로 진행한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..common.errors import FailureCategory, ProviderFailureError
from ..license.explanation import ReferenceChunk

PROVIDER = "RAG_ENGINE"


@dataclass(frozen=True)
class RagEngineConfig:
    """배포가 주입하는 설정. 값 자체는 Integration 이 환경변수로 넘긴다."""

    project_id: str
    region: str
    corpus_id: str
    corpus_version: str
    top_k: int = 3
    timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "RagEngineConfig":
        """``.env.example`` 에 선언된 이름을 그대로 읽는다."""
        missing = [
            name
            for name in ("GCP_PROJECT_ID", "RAG_REGION", "RAG_CORPUS_ID")
            if not env.get(name)
        ]
        if missing:
            raise ValueError(f"missing RAG configuration: {', '.join(missing)}")
        return cls(
            project_id=env["GCP_PROJECT_ID"],
            region=env["RAG_REGION"],
            corpus_id=env["RAG_CORPUS_ID"],
            corpus_version=env.get("RAG_CORPUS_VERSION", "unversioned"),
        )


class RagEngineRetriever:
    """관리형 RAG Engine 을 :class:`ReferenceRetriever` 규약에 맞춘다."""

    def __init__(self, config: RagEngineConfig) -> None:
        try:
            import vertexai  # noqa: PLC0415 - 선택 의존성
            from vertexai import rag  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈린다
            raise RuntimeError(
                "google-cloud-aiplatform is required for RagEngineRetriever; "
                "see agent-deliverables/agent-3-dependencies.md"
            ) from exc

        self._rag = rag
        self._config = config
        vertexai.init(project=config.project_id, location=config.region)
        self._corpus = (
            f"projects/{config.project_id}/locations/{config.region}"
            f"/ragCorpora/{config.corpus_id}"
        )

    @property
    def corpus_version(self) -> str:
        return self._config.corpus_version

    async def retrieve(
        self, query: str, *, filters: dict[str, str] | None = None, top_k: int | None = None
    ) -> list[ReferenceChunk]:
        limit = top_k or self._config.top_k
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._query, query, limit),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderFailureError(
                PROVIDER, FailureCategory.TIMEOUT, "retrieval timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - SDK 예외 종류가 넓다
            raise ProviderFailureError(
                PROVIDER, FailureCategory.UNAVAILABLE, type(exc).__name__
            ) from exc

        return [
            ReferenceChunk(
                source_id=context.source_display_name or "corpus",
                chunk_id=context.chunk_id or str(index),
                text=context.text or "",
                canonical_reference=context.source_uri or self._corpus,
                metadata={"corpus_version": self.corpus_version},
            )
            for index, context in enumerate(response)
        ]

    def _query(self, query: str, top_k: int):
        response = self._rag.retrieval_query(
            rag_resources=[self._rag.RagResource(rag_corpus=self._corpus)],
            text=query,
            rag_retrieval_config=self._rag.RagRetrievalConfig(top_k=top_k),
        )
        return list(response.contexts.contexts)
