"""Google Cloud RAG Engine 연동.

Application Plane 은 서울, RAG Engine 은 외부 GA region 에 둔다 (Blueprint 20).
그래서 region 을 하드코딩하지 않고 설정으로 받는다 (Agent 3 Spec 32).

``google-cloud-aiplatform`` SDK 대신 REST 를 직접 호출한다. 그 SDK 는 100MB 를
넘고 이 plane 이 쓰는 기능은 retrieveContexts 하나뿐이다. 자격증명 처리만
``google-auth`` 에 맡기고 HTTP 는 이미 쓰고 있는 httpx 로 보낸다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from ..common.errors import FailureCategory, ProviderFailureError
from ..license.explanation import ReferenceChunk

PROVIDER = "RAG_ENGINE"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True)
class RagEngineConfig:
    """배포가 주입하는 설정. 값 자체는 Integration 이 환경변수로 넘긴다."""

    project_id: str
    region: str
    corpus_id: str
    corpus_version: str = "unversioned"
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

    @property
    def corpus_resource(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.region}"
            f"/ragCorpora/{self.corpus_id}"
        )

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self.region}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.region}:retrieveContexts"
        )


class RagEngineRetriever:
    """관리형 RAG Engine 을 :class:`ReferenceRetriever` 규약에 맞춘다."""

    def __init__(
        self,
        config: RagEngineConfig,
        *,
        credentials: object | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if credentials is None:
            try:
                import google.auth  # noqa: PLC0415 - 선택 의존성
            except ImportError as exc:  # pragma: no cover - 설치 여부에 따라 갈린다
                raise RuntimeError(
                    "google-auth is required for RagEngineRetriever; "
                    "see agent-deliverables/agent-3-dependencies.md"
                ) from exc
            credentials, _project = google.auth.default(scopes=[SCOPE])

        self._config = config
        self._credentials = credentials
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

    @property
    def corpus_version(self) -> str:
        return self._config.corpus_version

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def retrieve(
        self,
        query: str,
        *,
        filters: dict[str, str] | None = None,
        top_k: int | None = None,
    ) -> list[ReferenceChunk]:
        payload = {
            "vertex_rag_store": {
                "rag_resources": [{"rag_corpus": self._config.corpus_resource}]
            },
            "query": {
                "text": query,
                "rag_retrieval_config": {"top_k": top_k or self._config.top_k},
            },
        }

        try:
            token = await asyncio.to_thread(self._access_token)
            response = await self._client.post(
                self._config.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderFailureError(
                PROVIDER, FailureCategory.TIMEOUT, "retrieval timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailureError(
                PROVIDER, FailureCategory.UNAVAILABLE, type(exc).__name__
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 자격증명 갱신 실패
            raise ProviderFailureError(
                PROVIDER, FailureCategory.AUTH, type(exc).__name__
            ) from exc

        if response.status_code >= 400:
            category = {
                401: FailureCategory.AUTH,
                403: FailureCategory.AUTH,
                429: FailureCategory.RATE_LIMITED,
            }.get(response.status_code, FailureCategory.UNAVAILABLE)
            raise ProviderFailureError(
                PROVIDER, category, f"HTTP {response.status_code}"
            )

        return self._to_chunks(response.json())

    # ------------------------------------------------------------ 내부

    def _access_token(self) -> str:
        """만료되었으면 갱신한다. 토큰은 로그에 남기지 않는다."""
        from google.auth.transport.requests import Request  # noqa: PLC0415

        if not getattr(self._credentials, "valid", False):
            self._credentials.refresh(Request())
        return self._credentials.token

    def _to_chunks(self, payload: dict) -> list[ReferenceChunk]:
        contexts = (payload.get("contexts") or {}).get("contexts") or []
        chunks: list[ReferenceChunk] = []
        for index, context in enumerate(contexts):
            uri = context.get("sourceUri") or self._config.corpus_resource
            chunks.append(
                ReferenceChunk(
                    source_id=context.get("sourceDisplayName") or "corpus",
                    chunk_id=str(context.get("chunkId") or index),
                    text=context.get("text") or "",
                    canonical_reference=uri,
                    metadata={"corpus_version": self.corpus_version},
                )
            )
        return chunks
