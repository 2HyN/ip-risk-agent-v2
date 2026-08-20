"""Private Cloud Storage staging for transient Local source text."""

from __future__ import annotations

import asyncio
import secrets

from google.api_core import exceptions as google_exceptions

from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.local.staging_store import StagingRef

_FORBIDDEN_METADATA_PARTS = ("path", "url", "token", "secret", "content", "auth")


class CloudStorageLocalStagingStore:
    def __init__(
        self,
        *,
        client,
        bucket_name: str,
        maximum_bytes: int = 1_000_000,
    ) -> None:
        if not 1 <= maximum_bytes <= 10_000_000:
            raise ValueError("staging maximum must be between 1 byte and 10 MB")
        self._bucket = client.bucket(bucket_name)
        self._maximum_bytes = maximum_bytes

    async def validate_bucket(self) -> None:
        await asyncio.to_thread(self._bucket.reload)
        uniform = self._bucket.iam_configuration.uniform_bucket_level_access_enabled
        if uniform is not True:
            raise RuntimeError("staging bucket must enforce uniform bucket-level access")

    async def put(self, payload: str, metadata_safe: dict[str, object]) -> StagingRef:
        encoded = payload.encode("utf-8")
        if not encoded or len(encoded) > self._maximum_bytes:
            raise ValueError("staging payload size is outside the allowed range")
        metadata = _safe_metadata(metadata_safe)
        object_name = f"staging/{secrets.token_urlsafe(32)}"
        blob = self._bucket.blob(object_name)
        blob.metadata = metadata
        blob.cache_control = "no-store"
        await asyncio.to_thread(
            blob.upload_from_string,
            encoded,
            content_type="text/plain; charset=utf-8",
            if_generation_match=0,
        )
        return StagingRef(object_name=object_name)

    async def get(self, ref: StagingRef) -> str:
        blob = self._blob(ref)
        try:
            data = await asyncio.to_thread(blob.download_as_bytes)
        except google_exceptions.NotFound as exc:
            raise NotFoundError(
                provider="local", safe_message="staging object was not found"
            ) from exc
        if len(data) > self._maximum_bytes:
            raise ValueError("staging object exceeds the allowed size")
        return data.decode("utf-8")

    async def delete(self, ref: StagingRef) -> None:
        try:
            await asyncio.to_thread(self._blob(ref).delete)
        except google_exceptions.NotFound:
            return

    def _blob(self, ref: StagingRef):
        if not ref.object_name.startswith("staging/") or ".." in ref.object_name:
            raise ValueError("invalid staging object reference")
        return self._bucket.blob(ref.object_name)


def _safe_metadata(values: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        normalized = str(key).lower()
        if any(part in normalized for part in _FORBIDDEN_METADATA_PARTS):
            raise ValueError("staging metadata contains a forbidden field")
        text = str(value)
        if len(key) > 64 or len(text) > 256:
            raise ValueError("staging metadata is too large")
        result[key] = text
    return result


__all__ = ["CloudStorageLocalStagingStore"]
