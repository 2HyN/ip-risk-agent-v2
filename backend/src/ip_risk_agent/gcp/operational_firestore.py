"""Firestore persistence for Source operational state.

These collections are deliberately prefixed with ``source_operational_`` and
never contain canonical Risk, Review, Membership, or raw source content.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Generic, Protocol, TypeVar

from google.cloud.firestore_v1 import async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel
from iprisk_contracts import SourceType

from ip_risk_agent.composition.device_auth import (
    DesktopDevice,
    DeviceMountBinding,
    DeviceStatus,
    EnrollmentChallenge,
)
from ip_risk_agent.composition.source_registration import (
    PendingConnectionStatus,
    PendingSourceConnection,
    SourceMountBinding,
)
from ip_risk_agent.connectors.common.credential_vault import CredentialRef

OAUTH_STATES = "source_operational_oauth_states"
PENDING_CONNECTIONS = "source_operational_pending_connections"
MOUNT_BINDINGS = "source_operational_mount_bindings"
DEVICE_CHALLENGES = "source_operational_device_challenges"
DEVICES = "source_operational_devices"
DEVICE_CREDENTIALS = "source_operational_device_credentials"
DEVICE_MOUNTS = "source_operational_device_mounts"
RUNTIME_COLLECTIONS = frozenset(
    {
        "source_operational_drive_runtime",
        "source_operational_drive_tracking",
        "source_operational_github_runtime",
        "source_operational_github_tracking",
        "source_operational_local_runtime",
    }
)
MAINTENANCE_COLLECTIONS = frozenset(
    {
        OAUTH_STATES,
        PENDING_CONNECTIONS,
        DEVICE_CHALLENGES,
        *RUNTIME_COLLECTIONS,
    }
)


@dataclass(frozen=True, slots=True)
class OperationalDocument:
    document_id: str
    data: dict


class OperationalFirestoreBackend(Protocol):
    async def get(self, collection: str, document_id: str) -> dict | None: ...
    async def put(self, collection: str, document_id: str, data: dict) -> None: ...
    async def delete(self, collection: str, document_id: str) -> None: ...
    async def query_one(self, collection: str, field: str, value: object) -> dict | None: ...
    async def query_many(
        self,
        collection: str,
        filters: Mapping[str, object],
        *,
        limit: int,
    ) -> tuple[dict, ...]: ...
    async def consume_unexpired(
        self, collection: str, document_id: str, now: datetime
    ) -> dict | None: ...
    async def scan_page(
        self,
        collection: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[OperationalDocument, ...], str | None]: ...


class GoogleOperationalFirestoreBackend:
    def __init__(self, client) -> None:
        self._client = client

    async def get(self, collection: str, document_id: str) -> dict | None:
        snapshot = await self._reference(collection, document_id).get()
        return _document(snapshot)

    async def put(self, collection: str, document_id: str, data: dict) -> None:
        await self._reference(collection, document_id).set(data)

    async def delete(self, collection: str, document_id: str) -> None:
        await self._reference(collection, document_id).delete()

    async def query_one(
        self, collection: str, field: str, value: object
    ) -> dict | None:
        query = self._client.collection(collection).where(
            filter=FieldFilter(field, "==", value)
        ).limit(1)
        async for snapshot in query.stream():
            return _document(snapshot)
        return None

    async def query_many(
        self,
        collection: str,
        filters: Mapping[str, object],
        *,
        limit: int,
    ) -> tuple[dict, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("operational query limit must be between 1 and 500")
        query = self._client.collection(collection)
        for field, value in filters.items():
            query = query.where(filter=FieldFilter(field, "==", value))
        results: list[dict] = []
        async for snapshot in query.limit(limit).stream():
            document = _document(snapshot)
            if document is not None:
                results.append(document)
        return tuple(results)

    async def consume_unexpired(
        self, collection: str, document_id: str, now: datetime
    ) -> dict | None:
        reference = self._reference(collection, document_id)
        transaction = self._client.transaction(max_attempts=5)

        @async_transactional
        async def consume(transaction):
            snapshot = await reference.get(transaction=transaction)
            data = _document(snapshot)
            if (
                data is None
                or data.get("consumed_at") is not None
                or not isinstance(data.get("expires_at"), datetime)
                or data["expires_at"] <= now
            ):
                return None
            transaction.update(reference, {"consumed_at": now})
            return data

        return await consume(transaction)

    async def scan_page(
        self,
        collection: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[OperationalDocument, ...], str | None]:
        if limit < 1 or limit > 500:
            raise ValueError("operational scan limit must be between 1 and 500")
        collection_ref = self._client.collection(collection)
        query = collection_ref.order_by("__name__")
        if cursor is not None:
            query = query.where(
                filter=FieldFilter("__name__", ">", collection_ref.document(cursor))
            )
        snapshots = []
        async for snapshot in query.limit(limit + 1).stream():
            snapshots.append(snapshot)
        has_more = len(snapshots) > limit
        selected = snapshots[:limit]
        documents = tuple(
            OperationalDocument(snapshot.id, document)
            for snapshot in selected
            if (document := _document(snapshot)) is not None
        )
        next_cursor = selected[-1].id if has_more and selected else None
        return documents, next_cursor

    def _reference(self, collection: str, document_id: str):
        return self._client.collection(collection).document(document_id)


class FirestoreOAuthStateStore:
    def __init__(
        self,
        backend: OperationalFirestoreBackend,
        *,
        ttl: timedelta = timedelta(minutes=10),
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        if ttl <= timedelta(0) or ttl > timedelta(hours=1):
            raise ValueError("OAuth state TTL must be between 0 and 1 hour")
        self._backend = backend
        self._ttl = ttl
        self._clock = clock

    async def save(self, state: str, context: dict) -> None:
        now = self._clock()
        await self._backend.put(
            OAUTH_STATES,
            _key(state),
            {
                "schema_version": 1,
                "context": _json_safe_context(context),
                "created_at": now,
                "expires_at": now + self._ttl,
                "consumed_at": None,
            },
        )

    async def consume(self, state: str) -> dict | None:
        data = await self._backend.consume_unexpired(
            OAUTH_STATES, _key(state), self._clock()
        )
        context = None if data is None else data.get("context")
        return dict(context) if isinstance(context, Mapping) else None


RuntimeRecord = TypeVar("RuntimeRecord", bound=BaseModel)


class FirestoreRuntimeStore(Generic[RuntimeRecord]):
    def __init__(
        self,
        backend: OperationalFirestoreBackend,
        *,
        collection: str,
        model: type[RuntimeRecord],
    ) -> None:
        if collection not in RUNTIME_COLLECTIONS:
            raise ValueError("runtime collection is not allow-listed")
        self._backend = backend
        self._collection = collection
        self._model = model

    async def load(self, key: str) -> RuntimeRecord | None:
        data = await self._backend.get(self._collection, _key(key))
        if data is None:
            return None
        return self._model.model_validate(data["record"])

    async def save(self, key: str, record: RuntimeRecord) -> None:
        await self._backend.put(
            self._collection,
            _key(key),
            {
                "schema_version": 1,
                "lookup_key_hash": _key(key),
                "record": record.model_dump(mode="python"),
                "updated_at": datetime.now(timezone.utc),
            },
        )

    async def delete(self, key: str) -> None:
        await self._backend.delete(self._collection, _key(key))

    async def find_one(self, field: str, value: object) -> RuntimeRecord | None:
        data = await self._backend.query_one(
            self._collection,
            f"record.{field}",
            value,
        )
        return None if data is None else self._model.model_validate(data["record"])

    async def find_many(
        self,
        filters: Mapping[str, object],
        *,
        limit: int = 100,
    ) -> tuple[RuntimeRecord, ...]:
        documents = await self._backend.query_many(
            self._collection,
            {f"record.{field}": value for field, value in filters.items()},
            limit=limit,
        )
        return tuple(
            self._model.model_validate(document["record"])
            for document in documents
        )

    async def page(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[RuntimeRecord, ...], str | None]:
        documents, next_cursor = await self._backend.scan_page(
            self._collection,
            cursor=cursor,
            limit=limit,
        )
        return (
            tuple(
                self._model.model_validate(document.data["record"])
                for document in documents
            ),
            next_cursor,
        )


class FirestoreMaintenanceStore:
    """Bounded access to operational records owned by scheduler maintenance."""

    def __init__(self, backend: OperationalFirestoreBackend) -> None:
        self._backend = backend

    async def page(
        self,
        collection: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[tuple[OperationalDocument, ...], str | None]:
        if collection not in MAINTENANCE_COLLECTIONS:
            raise ValueError("maintenance collection is not allow-listed")
        return await self._backend.scan_page(collection, cursor=cursor, limit=limit)

    async def delete(self, collection: str, document_id: str) -> None:
        if collection not in MAINTENANCE_COLLECTIONS:
            raise ValueError("maintenance collection is not allow-listed")
        await self._backend.delete(collection, document_id)


class FirestorePendingConnectionStore:
    def __init__(self, backend: OperationalFirestoreBackend) -> None:
        self._backend = backend
        self.lock = asyncio.Lock()

    async def get_pending(self, connection_id: str) -> PendingSourceConnection | None:
        return _pending(
            await self._backend.get(PENDING_CONNECTIONS, _key(connection_id))
        )

    async def get_pending_by_key(self, key: str) -> PendingSourceConnection | None:
        return _pending(
            await self._backend.query_one(PENDING_CONNECTIONS, "idempotency_key", key)
        )

    async def save_pending(self, value: PendingSourceConnection) -> None:
        await self._backend.put(
            PENDING_CONNECTIONS,
            _key(value.id),
            {
                "schema_version": 1,
                **asdict(value),
                "source_type": value.source_type.value,
                "status": value.status.value,
                "credential_ref": (
                    None
                    if value.credential_ref is None
                    else value.credential_ref.model_dump(mode="python")
                ),
            },
        )

    async def get_binding(self, registration_key: str) -> SourceMountBinding | None:
        return _binding(
            await self._backend.get(MOUNT_BINDINGS, _key(registration_key))
        )

    async def get_binding_for_mount(self, mount_id: str) -> SourceMountBinding | None:
        return _binding(
            await self._backend.query_one(MOUNT_BINDINGS, "mount_id", mount_id)
        )

    async def get_binding_for_connection(
        self, canonical_connection_id: str
    ) -> SourceMountBinding | None:
        return _binding(
            await self._backend.query_one(
                MOUNT_BINDINGS,
                "canonical_connection_id",
                canonical_connection_id,
            )
        )

    async def save_binding(self, value: SourceMountBinding) -> None:
        await self._backend.put(
            MOUNT_BINDINGS,
            _key(value.registration_key),
            {"schema_version": 1, **asdict(value)},
        )


class FirestoreDeviceAuthStore:
    def __init__(self, backend: OperationalFirestoreBackend) -> None:
        self._backend = backend
        self.lock = asyncio.Lock()

    async def save_challenge(self, challenge: EnrollmentChallenge) -> None:
        await self._backend.put(
            DEVICE_CHALLENGES,
            _key(challenge.token_hash),
            {"schema_version": 1, **asdict(challenge)},
        )

    async def get_challenge(self, token_hash: str) -> EnrollmentChallenge | None:
        data = await self._backend.get(DEVICE_CHALLENGES, _key(token_hash))
        return None if data is None else EnrollmentChallenge(**_without_schema(data))

    async def save_device(self, device: DesktopDevice) -> None:
        previous = await self.get_device(device.device_id)
        if previous is not None and previous.credential_hash != device.credential_hash:
            await self._backend.delete(
                DEVICE_CREDENTIALS, _key(previous.credential_hash)
            )
        await self._backend.put(
            DEVICES,
            _key(device.device_id),
            {
                "schema_version": 1,
                **asdict(device),
                "status": device.status.value,
            },
        )
        await self._backend.put(
            DEVICE_CREDENTIALS,
            _key(device.credential_hash),
            {"schema_version": 1, "device_id": device.device_id},
        )

    async def get_device_by_credential(
        self, credential_hash: str
    ) -> DesktopDevice | None:
        lookup = await self._backend.get(DEVICE_CREDENTIALS, _key(credential_hash))
        if lookup is None or not isinstance(lookup.get("device_id"), str):
            return None
        return await self.get_device(lookup["device_id"])

    async def get_device(self, device_id: str) -> DesktopDevice | None:
        data = await self._backend.get(DEVICES, _key(device_id))
        if data is None:
            return None
        values = _without_schema(data)
        values["status"] = DeviceStatus(values["status"])
        return DesktopDevice(**values)

    async def save_mount_binding(self, binding: DeviceMountBinding) -> None:
        await self._backend.put(
            DEVICE_MOUNTS,
            _key(binding.mount_id),
            {"schema_version": 1, **asdict(binding)},
        )

    async def get_mount_binding(self, mount_id: str) -> DeviceMountBinding | None:
        data = await self._backend.get(DEVICE_MOUNTS, _key(mount_id))
        return None if data is None else DeviceMountBinding(**_without_schema(data))


def _pending(data: dict | None) -> PendingSourceConnection | None:
    if data is None:
        return None
    values = _without_schema(data)
    values["source_type"] = SourceType(values["source_type"])
    values["status"] = PendingConnectionStatus(values["status"])
    credential = values.get("credential_ref")
    values["credential_ref"] = (
        None if credential is None else CredentialRef.model_validate(credential)
    )
    return PendingSourceConnection(**values)


def _binding(data: dict | None) -> SourceMountBinding | None:
    return None if data is None else SourceMountBinding(**_without_schema(data))


def _without_schema(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != "schema_version"}


def _document(snapshot) -> dict | None:
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    if not isinstance(data, Mapping):
        raise TypeError("operational Firestore document must be a mapping")
    return dict(data)


def _key(value: str) -> str:
    if not value:
        raise ValueError("operational lookup key must not be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_safe_context(context: dict) -> dict:
    allowed = {"risk_workspace_id", "owner_user_id", "provider", "return_path"}
    if any(key not in allowed for key in context):
        raise ValueError("OAuth state context contains an unexpected field")
    result: dict[str, str] = {}
    for key, value in context.items():
        if not isinstance(value, str) or not value or len(value) > 512:
            raise ValueError("OAuth state context must contain bounded strings")
        result[key] = value
    return result


__all__ = [
    "DEVICE_CHALLENGES",
    "MOUNT_BINDINGS",
    "MAINTENANCE_COLLECTIONS",
    "OAUTH_STATES",
    "PENDING_CONNECTIONS",
    "RUNTIME_COLLECTIONS",
    "FirestoreDeviceAuthStore",
    "FirestoreMaintenanceStore",
    "FirestoreOAuthStateStore",
    "FirestorePendingConnectionStore",
    "FirestoreRuntimeStore",
    "GoogleOperationalFirestoreBackend",
    "OperationalDocument",
    "OperationalFirestoreBackend",
]
