"""GCS 기반 ``LocalStagingStore``.

Desktop 이 올린 파일 내용을 워커가 읽을 때까지만 보관한다. 원본을 오래 두지
않는 것이 이 저장소의 존재 이유이므로, 객체마다 TTL 을 걸어 버킷 수명주기
규칙이 지우도록 한다 (Agent 2 Spec 45 항목 17).

객체 이름에 로컬 절대경로를 넣지 않는다. mount 스코프와 무작위 토큰만 쓴다.
"""

from __future__ import annotations

import asyncio
import secrets

from iprisk_contracts.common import SafeMetadata

from ip_risk_agent.connectors.common.errors import (
    NotFoundError,
    TemporaryUnavailableError,
)
from ip_risk_agent.connectors.local.staging_store import StagingRef

PROVIDER = "gcs-staging"

# 워커가 가져가기 전에 지워지면 분석이 실패한다. 재시도 여유를 포함해 잡는다.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class GcsLocalStagingStore:
    """``LocalStagingStore`` Protocol 의 운영 구현.

    SDK 가 동기라 ``asyncio.to_thread`` 로 감싼다.
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        prefix: str = "staging",
        client: object | None = None,
    ) -> None:
        if not bucket_name:
            raise ValueError("staging bucket name is required")
        self._bucket_name = bucket_name
        self._prefix = prefix.strip("/")
        self._client = client

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage  # noqa: PLC0415 - 지연 import

            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)

    def _object_name(self) -> str:
        # 내용이나 경로를 이름에 담지 않는다. 추측 불가능한 토큰만 쓴다.
        return f"{self._prefix}/{secrets.token_urlsafe(24)}"

    async def put(self, payload: str, metadata_safe: SafeMetadata) -> StagingRef:
        object_name = self._object_name()

        def _call() -> None:
            blob = self._bucket().blob(object_name)
            # metadata 는 safe 계약을 이미 통과한 값만 들어온다. 그대로 붙여
            # 운영에서 어떤 mount 의 객체인지 되짚을 수 있게 한다.
            blob.metadata = {str(k): str(v) for k, v in dict(metadata_safe).items()}
            blob.upload_from_string(payload, content_type="text/plain; charset=utf-8")

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001 - SDK 예외 종류가 넓다
            raise TemporaryUnavailableError(
                PROVIDER, "failed to write staging object"
            ) from exc
        return StagingRef(object_name=object_name)

    async def get(self, ref: StagingRef) -> str:
        from google.api_core import exceptions  # noqa: PLC0415

        def _call() -> str:
            blob = self._bucket().blob(ref.object_name)
            return blob.download_as_text(encoding="utf-8")

        try:
            return await asyncio.to_thread(_call)
        except exceptions.NotFound as exc:
            # TTL 로 이미 지워졌거나 잘못된 참조다. 빈 내용으로 위장하지 않는다.
            raise NotFoundError(
                PROVIDER, f"staging object not found: {ref.object_name}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise TemporaryUnavailableError(
                PROVIDER, "failed to read staging object"
            ) from exc

    async def delete(self, ref: StagingRef) -> None:
        from google.api_core import exceptions  # noqa: PLC0415

        def _call() -> None:
            try:
                self._bucket().blob(ref.object_name).delete()
            except exceptions.NotFound:
                # 이미 없는 것을 지우는 것은 성공으로 본다.
                pass

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001
            raise TemporaryUnavailableError(
                PROVIDER, "failed to delete staging object"
            ) from exc


__all__ = ["DEFAULT_TTL_SECONDS", "GcsLocalStagingStore"]
