"""Low-level Firestore backend with optimistic read/query expectations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1 import AsyncClient, AsyncTransaction, async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter

from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    RecordNotFoundError,
    UniqueConstraintViolation,
)

from .mappers import Document


@dataclass(frozen=True, slots=True)
class DocumentKey:
    collection: str
    document_id: str


@dataclass(frozen=True, slots=True)
class QueryFilter:
    field: str
    value: object
    operator: str = "=="


@dataclass(frozen=True, slots=True)
class StoredDocument:
    key: DocumentKey
    data: Document


@dataclass(frozen=True, slots=True)
class ReadExpectation:
    key: DocumentKey
    data: Document | None


@dataclass(frozen=True, slots=True)
class QueryExpectation:
    collection: str
    filters: tuple[QueryFilter, ...]
    documents: tuple[StoredDocument, ...]


@dataclass(frozen=True, slots=True)
class DocumentWrite:
    operation: Literal["create", "set", "delete"]
    key: DocumentKey
    data: Document | None = None


class FirestoreDocumentBackend(Protocol):
    async def get(self, key: DocumentKey) -> StoredDocument | None: ...

    async def query(
        self, collection: str, filters: tuple[QueryFilter, ...]
    ) -> tuple[StoredDocument, ...]: ...

    async def atomic_commit(
        self,
        *,
        reads: tuple[ReadExpectation, ...],
        queries: tuple[QueryExpectation, ...],
        writes: tuple[DocumentWrite, ...],
    ) -> None: ...


class GoogleFirestoreBackend:
    """Production backend; all SDK objects remain below this boundary."""

    def __init__(self, client: AsyncClient, *, max_attempts: int = 5) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._client = client
        self._max_attempts = max_attempts

    async def get(self, key: DocumentKey) -> StoredDocument | None:
        snapshot = await self._reference(key).get()
        return _stored(key.collection, snapshot)

    async def query(
        self, collection: str, filters: tuple[QueryFilter, ...]
    ) -> tuple[StoredDocument, ...]:
        query = self._query(collection, filters)
        documents = [
            stored
            async for snapshot in query.stream()
            if (stored := _stored(collection, snapshot)) is not None
        ]
        return tuple(sorted(documents, key=lambda item: item.key.document_id))

    async def atomic_commit(
        self,
        *,
        reads: tuple[ReadExpectation, ...],
        queries: tuple[QueryExpectation, ...],
        writes: tuple[DocumentWrite, ...],
    ) -> None:
        transaction = self._client.transaction(max_attempts=self._max_attempts)

        @async_transactional
        async def apply(transaction: AsyncTransaction) -> None:
            for expectation in reads:
                current = await self._transaction_get(transaction, expectation.key)
                current_data = None if current is None else current.data
                if current_data != expectation.data:
                    raise ConcurrencyConflictError(
                        f"document changed during transaction: "
                        f"{expectation.key.collection}/{expectation.key.document_id}"
                    )

            for expectation in queries:
                current = await self._transaction_query(
                    transaction, expectation.collection, expectation.filters
                )
                if current != expectation.documents:
                    raise ConcurrencyConflictError(
                        f"query result changed during transaction: {expectation.collection}"
                    )

            for write in writes:
                reference = self._reference(write.key)
                if write.operation == "create":
                    transaction.create(reference, _required_data(write))
                elif write.operation == "set":
                    transaction.set(reference, _required_data(write))
                else:
                    transaction.delete(reference)

        try:
            await apply(transaction)
        except google_exceptions.AlreadyExists as exc:
            raise UniqueConstraintViolation("Firestore document already exists") from exc
        except google_exceptions.NotFound as exc:
            raise RecordNotFoundError("Firestore document was not found") from exc
        except (google_exceptions.Aborted, google_exceptions.FailedPrecondition) as exc:
            raise ConcurrencyConflictError("Firestore transaction conflicted") from exc
        except ValueError as exc:
            if isinstance(exc.__cause__, google_exceptions.Aborted):
                raise ConcurrencyConflictError(
                    "Firestore transaction exhausted conflict retries"
                ) from exc
            raise

    def _reference(self, key: DocumentKey):
        return self._client.collection(key.collection).document(key.document_id)

    def _query(self, collection: str, filters: tuple[QueryFilter, ...]):
        query = self._client.collection(collection)
        for item in filters:
            query = query.where(filter=FieldFilter(item.field, item.operator, item.value))
        return query

    async def _transaction_get(
        self, transaction: AsyncTransaction, key: DocumentKey
    ) -> StoredDocument | None:
        snapshots = self._client.get_all([self._reference(key)], transaction=transaction)
        async for snapshot in snapshots:
            return _stored(key.collection, snapshot)
        return None

    async def _transaction_query(
        self,
        transaction: AsyncTransaction,
        collection: str,
        filters: tuple[QueryFilter, ...],
    ) -> tuple[StoredDocument, ...]:
        snapshots = self._query(collection, filters).stream(transaction=transaction)
        documents = [
            stored
            async for snapshot in snapshots
            if (stored := _stored(collection, snapshot)) is not None
        ]
        return tuple(sorted(documents, key=lambda item: item.key.document_id))


def _stored(collection: str, snapshot) -> StoredDocument | None:
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    if not isinstance(data, Mapping):
        raise TypeError("Firestore document data must be a mapping")
    return StoredDocument(
        key=DocumentKey(collection, snapshot.id),
        data=dict(data),
    )


def _required_data(write: DocumentWrite) -> Document:
    if write.data is None:
        raise ValueError(f"{write.operation} write requires document data")
    return write.data


__all__ = [
    "DocumentKey",
    "DocumentWrite",
    "FirestoreDocumentBackend",
    "GoogleFirestoreBackend",
    "QueryExpectation",
    "QueryFilter",
    "ReadExpectation",
    "StoredDocument",
]
