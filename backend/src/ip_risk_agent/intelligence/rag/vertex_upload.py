"""RAG Engine corpus 에 문서를 실제로 올린다.

## 왜 따로 있는가

``ingestion.py`` 는 매니페스트를 읽고 지문을 대조해 **올릴 것을 준비**하는 데까지만 한다.
올리는 쪽은 ``CorpusUploader`` 규약으로 비워 두었고, 지금까지 구현은
``InMemoryCorpusUploader`` 하나뿐이었다 — 즉 **아무도 실제로 올린 적이 없다.**
``scripts/prepare_rag_ingestion.py`` 가 언제나 ``external_write_performed: false`` 를
돌려주던 이유가 그것이다.

## SDK 대신 REST

``engine.py`` 가 검색에서 하는 것과 같다. ``google-cloud-aiplatform`` 은 100MB 를 넘고
여기서 쓰는 기능은 파일 업로드 하나뿐이다. 자격증명만 ``google-auth`` 에 맡기고 HTTP 는
이미 쓰는 httpx 로 보낸다.

## GCS 를 거치지 않는다

Vertex 에는 두 길이 있다 — GCS 에 올린 뒤 ``ragFiles:import`` 로 한 번에 가져오거나,
``ragFiles:upload`` 로 파일을 직접 보내거나. 후자를 쓴다. 버킷 권한과 lifecycle 규칙에
얽히지 않고(staging 접두사는 하루 뒤 지워진다), 실패한 파일만 다시 올릴 수 있으며,
장기 실행 작업(LRO)을 폴링하지 않아도 된다. 문서가 수백 편이라 호출이 많아지는 것이
대가이지만, corpus 갱신은 자주 하는 일이 아니다.

## 같은 이름은 지우고 다시 올린다

``ragFiles:upload`` 는 이름이 같아도 새 파일을 만든다. 그대로 두면 corpus 판본을 올릴
때마다 옛 문서가 남아 **검색 결과에 두 판본이 섞인다.** 그래서 올리기 전에 같은
``display_name`` 을 지운다.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from ..common.errors import FailureCategory, ProviderFailureError
from .ingestion import PreparedDocument

PROVIDER = "RAG_ENGINE"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"

#: 동시에 보내는 수. 올리는 것은 드문 작업이라 크게 잡지 않는다 — 할당량을 밀어내는
#: 것보다 조금 느린 편이 낫다.
_CONCURRENCY = 6


def _corpus_resource(project_id: str, region: str, corpus_id: str) -> str:
    return f"projects/{project_id}/locations/{region}/ragCorpora/{corpus_id}"


class VertexRagCorpusUploader:
    """``CorpusUploader`` 를 관리형 RAG Engine 에 잇는다.

    자격증명은 만들 때 한 번 받아 토큰을 갱신해 쓴다. 호출부는
    ``ingestion.ingest(manifest, uploader)`` 로 쓰던 것을 그대로 쓴다.
    """

    def __init__(
        self,
        *,
        project_id: str,
        region: str,
        corpus_id: str,
        credentials,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._corpus_id = corpus_id
        self._credentials = credentials
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------ 주소

    @property
    def corpus_resource(self) -> str:
        return _corpus_resource(self._project_id, self._region, self._corpus_id)

    @property
    def _base(self) -> str:
        return f"https://{self._region}-aiplatform.googleapis.com/v1"

    @property
    def _upload_base(self) -> str:
        return f"https://{self._region}-aiplatform.googleapis.com/upload/v1"

    # ------------------------------------------------------------------ 인증

    def _token(self) -> str:
        """만료됐으면 갱신한다. 수백 번 호출하는 동안 한 번은 만료된다."""
        from google.auth.transport.requests import Request as GoogleAuthRequest

        if not self._credentials.valid:
            self._credentials.refresh(GoogleAuthRequest())
        return self._credentials.token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    # ------------------------------------------------------------------ 동작

    async def list_files(self, client: httpx.AsyncClient) -> list[dict]:
        """corpus 에 지금 무엇이 있는지. 페이지를 끝까지 따라간다."""
        files: list[dict] = []
        page: str | None = None
        while True:
            params = {"pageSize": "100"}
            if page:
                params["pageToken"] = page
            response = await client.get(
                f"{self._base}/{self.corpus_resource}/ragFiles",
                params=params,
                headers=self._headers(),
            )
            self._raise_for_status(response, "list")
            payload = response.json()
            files.extend(payload.get("ragFiles", []))
            page = payload.get("nextPageToken")
            if not page:
                return files

    async def _delete(self, client: httpx.AsyncClient, name: str) -> None:
        response = await client.delete(
            f"{self._base}/{name}", headers=self._headers()
        )
        if response.status_code == 404:
            return
        self._raise_for_status(response, "delete")

    async def _upload_one(
        self,
        client: httpx.AsyncClient,
        document: PreparedDocument,
        corpus_version: str,
    ) -> None:
        """문서 하나를 multipart 로 보낸다.

        ``display_name`` 을 ``source_id`` 로 둔다 — 검색 결과의 ``sourceDisplayName``
        이 그 값으로 오고, 관련성 게이트가 그것으로 커버리지를 대조한다
        (``license/reference_gate.py``). 이름이 어긋나면 게이트가 **덮는 문서가 없다**
        고 판단해 근거가 하나도 안 붙는다.
        """
        metadata = {
            "rag_file": {
                "display_name": document.source_id,
                "description": json.dumps(
                    {
                        "corpus_version": corpus_version,
                        "document_version": document.version,
                        "canonical_reference": document.canonical_reference,
                        **document.metadata,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            }
        }
        response = await client.post(
            f"{self._upload_base}/{self.corpus_resource}/ragFiles:upload",
            headers=self._headers(),
            files={
                "metadata": (
                    None,
                    json.dumps(metadata, ensure_ascii=True),
                    "application/json",
                ),
                "file": (
                    f"{document.source_id}.md",
                    document.text.encode("utf-8"),
                    "text/markdown",
                ),
            },
        )
        self._raise_for_status(response, f"upload:{document.source_id}")

    async def upload(
        self, documents: list[PreparedDocument], corpus_version: str
    ) -> int:
        """``CorpusUploader`` 규약. 올린 문서 수를 돌려준다.

        올리기 전에 **같은 이름의 옛 파일을 지운다.** 지우지 않으면 판본이 섞이고,
        섞인 corpus 는 ``corpus_version`` 이 내용을 설명하지 못하게 만든다 — 그러면
        §5.6 이 요구하는 감사가 성립하지 않는다.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            existing = await self.list_files(client)
            wanted = {document.source_id for document in documents}
            stale = [
                item["name"]
                for item in existing
                if item.get("displayName") in wanted and item.get("name")
            ]
            for name in stale:
                await self._delete(client, name)

            semaphore = asyncio.Semaphore(_CONCURRENCY)

            async def send(document: PreparedDocument) -> None:
                async with semaphore:
                    await self._upload_one(client, document, corpus_version)

            await asyncio.gather(*(send(document) for document in documents))
        return len(documents)

    # ------------------------------------------------------------------ 오류

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str) -> None:
        if response.status_code < 400:
            return
        category = (
            FailureCategory.NOT_FOUND
            if response.status_code == 404
            else FailureCategory.UNAVAILABLE
        )
        # 본문에는 자격증명이 없지만 provider 응답을 통째로 남기지 않는다는 규칙을
        # 지켜 상태 코드와 연산 이름만 싣는다.
        raise ProviderFailureError(
            PROVIDER, category, f"{operation} failed with HTTP {response.status_code}"
        )


__all__ = ["VertexRagCorpusUploader"]
