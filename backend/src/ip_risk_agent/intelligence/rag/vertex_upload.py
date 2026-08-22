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
from .ingestion import PreparedDocument, checksum

PROVIDER = "RAG_ENGINE"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"

#: 동시에 보내는 수. 올리는 것은 드문 작업이라 크게 잡지 않는다 — 할당량을 밀어내는
#: 것보다 조금 느린 편이 낫다. 6 으로 두었더니 700 편을 올리는 중에 429 를 맞았다.
_CONCURRENCY = 3

#: 429 와 5xx 를 만났을 때 다시 보내는 횟수. corpus 를 통째로 올리면 수백 번 호출하므로
#: 한 번의 일시적 거절로 전체가 멈추면 안 된다.
_MAX_ATTEMPTS = 6

#: 재시도 간격의 밑값(초). 실제로는 2 의 거듭제곱으로 늘린다.
_BACKOFF_BASE = 2.0


def _corpus_resource(project_id: str, region: str, corpus_id: str) -> str:
    return f"projects/{project_id}/locations/{region}/ragCorpora/{corpus_id}"


def display_key(name: str) -> str:
    """이름을 대조 가능한 형태로 맞춘다.

    corpus 에는 이름이 두 모양으로 들어가 있을 수 있다. 손으로 올린 것은 파일명
    그대로 ``agpl-3.0-obligations.md`` 이고, 이 업로더는 ``source_id`` 만 쓴다.
    그대로 비교하면 **같은 문서를 다른 것으로 보아** 옛 것을 지우지 못하고 새 것을
    덧올려 corpus 에 두 판본이 남는다.

    관련성 게이트가 검색 결과 이름을 맞출 때 쓰는 규칙과 같게 둔다
    (``license/reference_gate.py`` 의 ``_covered_identifiers``) — 경로를 떼고,
    소문자로 내리고, ``.md`` 를 뗀다. 두 곳이 다른 규칙을 쓰면 한쪽이 맞다고 본 것을
    다른 쪽이 아니라고 본다.
    """
    key = name.rsplit("/", 1)[-1].strip().lower()
    if key.endswith(".md"):
        key = key[: -len(".md")]
    return key


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

    # ------------------------------------------------------------------ 재시도

    async def _send(
        self, client: httpx.AsyncClient, method: str, url: str, **kwargs
    ) -> httpx.Response:
        """429 와 5xx 는 다시 보낸다.

        corpus 를 통째로 올리면 700 번 가까이 호출한다. 그 사이 한 번의 일시적 거절로
        전체가 멈추면 **부분 적재된 corpus** 가 남고, 그때 ``corpus_version`` 은 내용을
        설명하지 못한다 — 실제로 그렇게 한 번 죽었다(``spdx-eupl-1.0`` 에서 429).

        서버가 ``Retry-After`` 를 주면 그 값을 따르고, 없으면 2 의 거듭제곱으로 늘린다.
        재시도해도 소용없는 4xx(권한·형식)는 그대로 올린다.
        """
        delay = _BACKOFF_BASE
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = await client.request(
                method, url, headers=self._headers(), **kwargs
            )
            if response.status_code < 400:
                return response
            retriable = response.status_code == 429 or response.status_code >= 500
            if not retriable or attempt == _MAX_ATTEMPTS:
                return response
            hinted = response.headers.get("Retry-After")
            try:
                wait = float(hinted) if hinted else delay
            except ValueError:
                wait = delay
            await asyncio.sleep(min(wait, 60.0))
            delay *= 2
        return response  # pragma: no cover - 위 루프가 언제나 돌려준다

    # ------------------------------------------------------------------ 동작

    async def list_files(self, client: httpx.AsyncClient) -> list[dict]:
        """corpus 에 지금 무엇이 있는지. 페이지를 끝까지 따라간다."""
        files: list[dict] = []
        page: str | None = None
        while True:
            params = {"pageSize": "100"}
            if page:
                params["pageToken"] = page
            response = await self._send(
                client,
                "GET",
                f"{self._base}/{self.corpus_resource}/ragFiles",
                params=params,
            )
            self._raise_for_status(response, "list")
            payload = response.json()
            files.extend(payload.get("ragFiles", []))
            page = payload.get("nextPageToken")
            if not page:
                return files

    async def _delete(self, client: httpx.AsyncClient, name: str) -> None:
        response = await self._send(client, "DELETE", f"{self._base}/{name}")
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
                # 여기 적은 것이 **나중에 확인할 수 있는 전부**다. 목록 API 는 본문을
                # 돌려주지 않으므로, 지문을 함께 남기지 않으면 "올라간 것이 올리려던
                # 것과 같은가" 를 물을 방법이 없다.
                "description": json.dumps(
                    {
                        "corpus_version": corpus_version,
                        "document_version": document.version,
                        "checksum": checksum(document.text),
                        "canonical_reference": document.canonical_reference,
                        **document.metadata,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            }
        }
        response = await self._send(
            client,
            "POST",
            f"{self._upload_base}/{self.corpus_resource}/ragFiles:upload",
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

            # 이미 같은 판본·같은 지문으로 올라가 있는 것은 건너뛴다. 700 편을 올리다
            # 끊기면 처음부터 다시 하는 대신 남은 것만 이어서 올릴 수 있어야 한다.
            done: dict[str, int] = {}
            for item in existing:
                key = display_key(item.get("displayName", ""))
                try:
                    stamped = json.loads(item.get("description") or "{}")
                except json.JSONDecodeError:
                    stamped = {}
                if stamped.get("corpus_version") == corpus_version:
                    done[key] = done.get(key, 0) + 1

            pending = [
                document
                for document in documents
                if done.get(display_key(document.source_id), 0) != 1
            ]

            # 다시 올릴 것과 같은 이름인 옛 파일만 지운다. 판본이 맞아 건너뛰는 것은
            # 그대로 둔다 — 지웠다 다시 올리면 이어 올리는 뜻이 없다.
            retry_keys = {display_key(document.source_id) for document in pending}
            stale = [
                item["name"]
                for item in existing
                if display_key(item.get("displayName", "")) in retry_keys
                and item.get("name")
            ]
            for name in stale:
                await self._delete(client, name)

            semaphore = asyncio.Semaphore(_CONCURRENCY)

            async def send(document: PreparedDocument) -> None:
                async with semaphore:
                    await self._upload_one(client, document, corpus_version)

            await asyncio.gather(*(send(document) for document in pending))
        return len(pending)

    # ------------------------------------------------------------------ 확인

    async def audit(
        self, documents: list[PreparedDocument], corpus_version: str
    ) -> dict[str, object]:
        """corpus 에 올라간 것이 올리려던 것과 같은가.

        올리기는 성공했는데 **틀린 것이 올라가 있는** 경우가 조용하다. 그래서 올린 뒤에
        다시 물어본다. 목록 API 는 본문을 돌려주지 않으므로 업로드할 때 ``description``
        에 남긴 지문과 판본을 대조한다.

        보는 것은 넷이다.

        * **빠진 것** — 매니페스트에 있는데 corpus 에 없다. 업로드가 실패했거나
          이름이 어긋났다.
        * **중복** — 같은 이름이 둘 이상이다. 지우고 올리는 단계가 걸러야 했던 것이고,
          남으면 검색이 두 판본을 섞는다.
        * **어긋난 지문·판본** — 이름은 맞는데 내용이 다르다.
        * **매니페스트 밖** — corpus 에 있는데 승인 목록에 없다. `approved_for_rag` 가
          관문이라고 해 놓고 관문을 지나지 않은 것이 남아 있는 상태다.

        고치지 않는다. 무엇이 어긋났는지만 돌려준다 — 지우는 것은 사람이 정한다.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            existing = await self.list_files(client)

        by_name: dict[str, list[dict]] = {}
        for item in existing:
            by_name.setdefault(display_key(item.get("displayName", "")), []).append(item)

        expected = {display_key(d.source_id): d for d in documents}
        missing: list[str] = []
        duplicated: list[str] = []
        mismatched: list[dict[str, str]] = []

        for source_id, document in expected.items():
            found = by_name.get(source_id, [])
            if not found:
                missing.append(source_id)
                continue
            if len(found) > 1:
                duplicated.append(source_id)
            want = checksum(document.text)
            for item in found:
                try:
                    stamped = json.loads(item.get("description") or "{}")
                except json.JSONDecodeError:
                    stamped = {}
                if stamped.get("checksum") != want:
                    mismatched.append({"source_id": source_id, "reason": "checksum"})
                elif stamped.get("corpus_version") != corpus_version:
                    mismatched.append(
                        {
                            "source_id": source_id,
                            "reason": "corpus_version",
                            "found": str(stamped.get("corpus_version")),
                        }
                    )

        unexpected = sorted(name for name in by_name if name not in expected)
        return {
            "corpus_resource": self.corpus_resource,
            "corpus_version": corpus_version,
            "expected": len(expected),
            "found": len(existing),
            "missing": sorted(missing),
            "duplicated": sorted(duplicated),
            "mismatched": mismatched,
            "unexpected": unexpected,
            "clean": not (missing or duplicated or mismatched or unexpected),
        }

    async def prune(self, names: list[str]) -> int:
        """매니페스트 밖 문서를 지운다. 사람이 목록을 보고 부른다."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            existing = await self.list_files(client)
            keys = {display_key(name) for name in names}
            targets = [
                item["name"]
                for item in existing
                if display_key(item.get("displayName", "")) in keys
                and item.get("name")
            ]
            for name in targets:
                await self._delete(client, name)
        return len(targets)

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


__all__ = ["VertexRagCorpusUploader", "display_key"]
