"""Agent 2 Spec 30번 LocalStagingStore. Cloud worker가 로컬 파일시스템에
직접 접근할 수 없으므로, Desktop이 미리 올려둔 content를 여기서 잠깐 보관한다.

payload를 str(텍스트)로 단순화했다 — 지금 범위(code/manifest/문서 텍스트)엔
충분하고, 바이너리가 필요해지면 이 타입만 확장하면 된다.
"""

from __future__ import annotations

from typing import Protocol

from iprisk_contracts.common import SafeMetadata, StrictModel

from ..common.errors import NotFoundError


class StagingRef(StrictModel):
    object_name: str


class LocalStagingStore(Protocol):
    async def put(self, payload: str, metadata_safe: SafeMetadata) -> StagingRef: ...

    async def get(self, ref: StagingRef) -> str: ...

    async def delete(self, ref: StagingRef) -> None: ...


class InMemoryLocalStagingStore:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._counter = 0

    async def put(self, payload: str, metadata_safe: SafeMetadata) -> StagingRef:
        self._counter += 1
        object_name = f"staging-{self._counter}"
        self._store[object_name] = payload
        return StagingRef(object_name=object_name)

    async def get(self, ref: StagingRef) -> str:
        try:
            return self._store[ref.object_name]
        except KeyError as exc:
            raise NotFoundError(
                provider="local", safe_message=f"staging object not found: {ref.object_name}"
            ) from exc

    async def delete(self, ref: StagingRef) -> None:
        self._store.pop(ref.object_name, None)
