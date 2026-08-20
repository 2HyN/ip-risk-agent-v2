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


def _threshold(raw: str | None) -> float | None:
    """빈 문자열이나 잘못된 값이면 기본값을 쓴다. 끄려면 명시적으로 "none"."""
    if raw is None or not raw.strip():
        return 0.6
    if raw.strip().lower() in {"none", "off", "disabled"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return 0.6


@dataclass(frozen=True)
class RagEngineConfig:
    """배포가 주입하는 설정. 값 자체는 Integration 이 환경변수로 넘긴다."""

    project_id: str
    region: str
    corpus_id: str
    corpus_version: str = "unversioned"
    top_k: int = 3
    timeout_seconds: float = 15.0
    # 관련도가 낮은 조각은 근거로 쓰지 않는다.
    #
    # corpus 에 없는 라이선스를 물어도 검색은 top_k 만큼 무언가를 돌려준다.
    # 그대로 근거로 붙이면 "이 점이 GPL-3.0 과 다르다"고 적힌 AGPL 문서가
    # GPL-3.0 의 근거가 된다. ID 무결성 검증과 프롬프트 제약을 **모두 통과한
    # 채로** 틀린 근거가 나가는 유일한 경로다.
    #
    # RAG Engine 의 거리는 작을수록 가깝다. 이 값보다 먼 조각은 버린다.
    vector_distance_threshold: float | None = 0.6

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
            vector_distance_threshold=_threshold(env.get("RAG_DISTANCE_THRESHOLD")),
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
                    "see docs/DEPENDENCIES.md"
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
        retrieval_config: dict = {"top_k": top_k or self._config.top_k}
        threshold = self._config.vector_distance_threshold
        if threshold is not None:
            # 관련도가 낮은 조각은 아예 받지 않는다.
            retrieval_config["filter"] = {"vector_distance_threshold": threshold}

        rag_resource: dict = {"rag_corpus": self._config.corpus_resource}
        if filters:
            # 매니페스트의 jurisdiction/tags 같은 metadata 로 좁힌다.
            # 이 인자를 받고도 쓰지 않으면 corpus 를 관할별로 나눈 의미가 없다.
            rag_resource["rag_file_ids"] = []
            retrieval_config["metadata_filter"] = {
                "filters": [
                    {"key": key, "value": value} for key, value in filters.items()
                ]
            }

        payload = {
            "vertex_rag_store": {"rag_resources": [rag_resource]},
            "query": {"text": query, "rag_retrieval_config": retrieval_config},
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
        threshold = self._config.vector_distance_threshold
        chunks: list[ReferenceChunk] = []
        for index, context in enumerate(contexts):
            # 서버가 필터를 무시하거나 형식이 바뀌어도 여기서 한 번 더 막는다.
            distance = context.get("distance")
            if (
                threshold is not None
                and isinstance(distance, (int, float))
                and distance > threshold
            ):
                continue
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
