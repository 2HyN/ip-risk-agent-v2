"""Source Plane 운영 상태와 조회 포트의 Firestore 구현.

Source Plane 은 Protocol 만 정의하고 실제 저장은 Integration 이 맡는다
(``connectors/common/runtime_store.py`` 모듈 주석). 여기 있는 collection 은 전부
Integration 소유이며 Control 의 canonical collection 과 겹치지 않는다.

Risk/Review/Membership 상태는 여기 넣지 않는다. connector 자신의 운영 상태와
provider 식별자 매핑만 다룬다 (Master Spec 38).
"""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

from iprisk_contracts.common import MountRef, SourceType, StrictModel

from ip_risk_agent.connectors.common.credential_vault import CredentialRef
from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.github.connection_lookup import GitHubConnectionContext
from ip_risk_agent.connectors.google_drive.connection_lookup import (
    DriveConnectionContext,
)

Record = TypeVar("Record", bound=StrictModel)

# Integration 소유 collection. canonical 이름과 구분되도록 접두사를 붙인다.
RUNTIME_COLLECTION = "integration_source_runtime"
TRACKING_SCOPE_COLLECTION = "integration_tracking_scopes"
MOUNT_BINDING_COLLECTION = "integration_mount_bindings"
CONNECTION_BINDING_COLLECTION = "integration_connection_bindings"


class _FirestoreCollection:
    """지연 초기화하는 Firestore collection 핸들."""

    def __init__(
        self,
        collection: str,
        *,
        project_id: str,
        database: str = "(default)",
        client: object | None = None,
    ) -> None:
        if not project_id:
            raise ValueError("project_id is required")
        self._collection = collection
        self._project_id = project_id
        self._database = database
        self._client = client

    def _handle(self):
        if self._client is None:
            from google.cloud import firestore  # noqa: PLC0415 - 지연 import

            self._client = firestore.Client(
                project=self._project_id, database=self._database
            )
        return self._client.collection(self._collection)

    async def read(self, key: str) -> dict | None:
        def _call() -> dict | None:
            snapshot = self._handle().document(key).get()
            return snapshot.to_dict() if snapshot.exists else None

        return await asyncio.to_thread(_call)

    async def write(self, key: str, payload: dict) -> None:
        await asyncio.to_thread(lambda: self._handle().document(key).set(payload))

    async def remove(self, key: str) -> None:
        await asyncio.to_thread(lambda: self._handle().document(key).delete())

    async def query(self, field: str, value: object) -> list[dict]:
        def _call() -> list[dict]:
            documents = self._handle().where(field, "==", value).stream()
            return [document.to_dict() or {} for document in documents]

        return await asyncio.to_thread(_call)


class FirestoreRuntimeStore(Generic[Record]):
    """``RuntimeStore`` Protocol 의 운영 구현.

    ``DriveRuntime`` / ``GitHubRuntime`` / ``LocalRuntime`` / ``DriveTrackingScope``
    등 Pydantic 모델이면 무엇이든 받는다. 모델을 그대로 직렬화하므로 필드가
    늘어도 이 코드를 고칠 필요가 없다.
    """

    def __init__(
        self,
        model: type[Record],
        *,
        project_id: str,
        collection: str = RUNTIME_COLLECTION,
        database: str = "(default)",
        client: object | None = None,
    ) -> None:
        self._model = model
        self._store = _FirestoreCollection(
            collection, project_id=project_id, database=database, client=client
        )

    async def load(self, key: str) -> Record | None:
        payload = await self._store.read(key)
        if payload is None:
            return None
        return self._model.model_validate(payload)

    async def save(self, key: str, record: Record) -> None:
        await self._store.write(key, record.model_dump(mode="json"))

    async def delete(self, key: str) -> None:
        await self._store.remove(key)


class FirestoreMountBindingStore:
    """mount/connection 과 provider 식별자를 잇는 Integration 소유 매핑.

    Drive·GitHub 의 여러 조회 포트가 결국 같은 정보를 다른 각도로 묻는다.
    한 곳에 모아 두고 각 Protocol 어댑터가 이것을 읽게 한다.
    """

    def __init__(
        self,
        *,
        project_id: str,
        database: str = "(default)",
        client: object | None = None,
    ) -> None:
        self._mounts = _FirestoreCollection(
            MOUNT_BINDING_COLLECTION,
            project_id=project_id,
            database=database,
            client=client,
        )
        self._connections = _FirestoreCollection(
            CONNECTION_BINDING_COLLECTION,
            project_id=project_id,
            database=database,
            client=client,
        )

    # -------------------------------------------------------------- 쓰기

    async def bind_connection(
        self,
        connection_id: str,
        *,
        source_type: SourceType,
        risk_workspace_id: str,
        owner_user_id: str,
        connection_key: str,
        credential_ref: CredentialRef | None = None,
        installation_id: str | None = None,
    ) -> None:
        await self._connections.write(
            connection_id,
            {
                "connection_id": connection_id,
                "source_type": source_type.value,
                "risk_workspace_id": risk_workspace_id,
                "owner_user_id": owner_user_id,
                # Mount 를 등록할 때 Control 에 넘길 provider 키.
                # 이것이 없으면 연결부터 다시 해야 한다.
                "connection_key": connection_key,
                "credential_ref": (
                    credential_ref.model_dump(mode="json") if credential_ref else None
                ),
                "installation_id": installation_id,
            },
        )

    async def bind_mount(
        self,
        mount_ref: MountRef,
        *,
        connection_id: str,
        watch_channel_id: str | None = None,
        repository_full_name: str | None = None,
    ) -> None:
        await self._mounts.write(
            mount_ref.mount_id,
            {
                "mount": mount_ref.model_dump(mode="json"),
                "connection_id": connection_id,
                "watch_channel_id": watch_channel_id,
                "repository_full_name": repository_full_name,
            },
        )

    # -------------------------------------------------------------- 읽기

    async def connection(self, connection_id: str) -> dict | None:
        return await self._connections.read(connection_id)

    async def mount(self, mount_id: str) -> dict | None:
        return await self._mounts.read(mount_id)

    async def mounts_by_channel(self, channel_id: str) -> list[dict]:
        return await self._mounts.query("watch_channel_id", channel_id)

    async def mounts_by_repository(self, full_name: str) -> list[dict]:
        return await self._mounts.query("repository_full_name", full_name)

    async def resolve_workspace(self, connection_id: str) -> str | None:
        record = await self.connection(connection_id)
        return record.get("risk_workspace_id") if record else None


# ------------------------------------------------------------------- Drive


class BoundDriveConnectionLookup:
    """``DriveConnectionLookup`` — mount_id 로 connection 과 credential 을 찾는다."""

    def __init__(self, bindings: FirestoreMountBindingStore) -> None:
        self._bindings = bindings

    async def resolve(self, mount_id: str) -> DriveConnectionContext:
        mount = await self._bindings.mount(mount_id)
        connection_id = (mount or {}).get("connection_id")
        record = (
            await self._bindings.connection(connection_id) if connection_id else None
        )
        credential = (record or {}).get("credential_ref")
        if not connection_id or credential is None:
            raise NotFoundError(
                provider="google_drive",
                safe_message=f"no connection registered for mount {mount_id}",
            )
        return DriveConnectionContext(
            connection_id=connection_id,
            credential_ref=CredentialRef.model_validate(credential),
        )


class BoundDriveConnectionCredentialLookup:
    """``DriveConnectionCredentialLookup`` — mount 이전 단계(Picker)에서 쓴다."""

    def __init__(self, bindings: FirestoreMountBindingStore) -> None:
        self._bindings = bindings

    async def resolve_credential_ref(self, connection_id: str) -> CredentialRef:
        record = await self._bindings.connection(connection_id)
        credential = (record or {}).get("credential_ref")
        if credential is None:
            raise NotFoundError(
                provider="google_drive",
                safe_message=(
                    f"no credential registered for connection {connection_id}"
                ),
            )
        return CredentialRef.model_validate(credential)


class BoundDriveChannelMountResolver:
    """``DriveChannelMountResolver`` — webhook channel 로 Mount 를 되짚는다."""

    def __init__(self, bindings: FirestoreMountBindingStore) -> None:
        self._bindings = bindings

    async def resolve_mount(self, channel_id: str) -> MountRef | None:
        for record in await self._bindings.mounts_by_channel(channel_id):
            mount = record.get("mount")
            if isinstance(mount, dict):
                return MountRef.model_validate(mount)
        return None


# ------------------------------------------------------------------ GitHub


class BoundGitHubConnectionLookup:
    """``GitHubConnectionLookup`` — mount_id 로 installation 을 찾는다."""

    def __init__(self, bindings: FirestoreMountBindingStore) -> None:
        self._bindings = bindings

    async def resolve(self, mount_id: str) -> GitHubConnectionContext:
        mount = await self._bindings.mount(mount_id)
        connection_id = (mount or {}).get("connection_id")
        record = (
            await self._bindings.connection(connection_id) if connection_id else None
        )
        installation_id = (record or {}).get("installation_id")
        if not installation_id:
            raise NotFoundError(
                provider="github",
                safe_message=f"no installation registered for mount {mount_id}",
            )
        return GitHubConnectionContext(installation_id=str(installation_id))


class BoundGitHubConnectionInstallationLookup:
    """``GitHubConnectionInstallationLookup`` — 저장소 목록 조회 단계에서 쓴다."""

    def __init__(self, bindings: FirestoreMountBindingStore) -> None:
        self._bindings = bindings

    async def resolve_installation_id(self, connection_id: str) -> str:
        record = await self._bindings.connection(connection_id)
        installation_id = (record or {}).get("installation_id")
        if not installation_id:
            raise NotFoundError(
                provider="github",
                safe_message=(
                    f"no installation registered for connection {connection_id}"
                ),
            )
        return str(installation_id)


class BoundGitHubMountResolver:
    """``GitHubMountResolver`` — webhook 의 owner/repo 로 Mount 들을 찾는다."""

    def __init__(self, bindings: FirestoreMountBindingStore) -> None:
        self._bindings = bindings

    async def resolve_mounts(self, owner: str, repo: str) -> list[MountRef]:
        mounts: list[MountRef] = []
        for record in await self._bindings.mounts_by_repository(f"{owner}/{repo}"):
            mount = record.get("mount")
            if isinstance(mount, dict):
                mounts.append(MountRef.model_validate(mount))
        return mounts


__all__ = [
    "BoundDriveChannelMountResolver",
    "BoundDriveConnectionCredentialLookup",
    "BoundDriveConnectionLookup",
    "BoundGitHubConnectionInstallationLookup",
    "BoundGitHubConnectionLookup",
    "BoundGitHubMountResolver",
    "CONNECTION_BINDING_COLLECTION",
    "FirestoreMountBindingStore",
    "FirestoreRuntimeStore",
    "MOUNT_BINDING_COLLECTION",
    "RUNTIME_COLLECTION",
    "TRACKING_SCOPE_COLLECTION",
]
