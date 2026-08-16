"""Unit-of-work document session with read-your-writes and optimistic CAS."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping

from ip_risk_agent.application.repositories import (
    RecordNotFoundError,
    TransactionClosedError,
    UniqueConstraintViolation,
)

from .backend import (
    DocumentKey,
    DocumentWrite,
    FirestoreDocumentBackend,
    QueryExpectation,
    QueryFilter,
    ReadExpectation,
    StoredDocument,
)
from .mappers import Document

_DELETED = object()


class FirestoreDocumentSession:
    def __init__(self, backend: FirestoreDocumentBackend) -> None:
        self._backend = backend
        self._open = True
        self._original_reads: OrderedDict[DocumentKey, Document | None] = OrderedDict()
        self._query_expectations: OrderedDict[
            tuple[str, tuple[QueryFilter, ...]], QueryExpectation
        ] = OrderedDict()
        self._overlay: dict[DocumentKey, Document | object] = {}
        self._writes: OrderedDict[DocumentKey, DocumentWrite] = OrderedDict()

    def ensure_open(self) -> None:
        if not self._open:
            raise TransactionClosedError("Firestore unit of work is not active")

    @property
    def is_open(self) -> bool:
        return self._open

    async def get(self, collection: str, document_id: str) -> Document | None:
        self.ensure_open()
        key = DocumentKey(collection, document_id)
        if key in self._overlay:
            value = self._overlay[key]
            return None if value is _DELETED else dict(value)
        stored = await self._backend.get(key)
        data = None if stored is None else stored.data
        self._original_reads.setdefault(key, None if data is None else dict(data))
        self._overlay[key] = _DELETED if data is None else dict(data)
        return None if data is None else dict(data)

    async def query(
        self, collection: str, filters: tuple[QueryFilter, ...]
    ) -> tuple[StoredDocument, ...]:
        self.ensure_open()
        query_key = (collection, filters)
        if query_key not in self._query_expectations:
            documents = await self._backend.query(collection, filters)
            expectation = QueryExpectation(collection, filters, documents)
            self._query_expectations[query_key] = expectation
            for stored in documents:
                self._original_reads.setdefault(stored.key, dict(stored.data))
                self._overlay.setdefault(stored.key, dict(stored.data))

        effective: dict[str, StoredDocument] = {
            item.key.document_id: item
            for item in self._query_expectations[query_key].documents
        }
        for key, value in self._overlay.items():
            if key.collection != collection:
                continue
            if value is _DELETED:
                effective.pop(key.document_id, None)
            elif _matches(value, filters):
                effective[key.document_id] = StoredDocument(key, dict(value))
            else:
                effective.pop(key.document_id, None)
        return tuple(effective[key] for key in sorted(effective))

    async def create(self, collection: str, document_id: str, data: Document) -> None:
        self.ensure_open()
        key = DocumentKey(collection, document_id)
        if await self.get(collection, document_id) is not None:
            raise UniqueConstraintViolation(f"document already exists: {collection}/{document_id}")
        document = dict(data)
        self._overlay[key] = document
        self._writes[key] = DocumentWrite("create", key, document)

    async def set(self, collection: str, document_id: str, data: Document) -> None:
        self.ensure_open()
        key = DocumentKey(collection, document_id)
        if await self.get(collection, document_id) is None:
            raise RecordNotFoundError(f"document was not found: {collection}/{document_id}")
        document = dict(data)
        self._overlay[key] = document
        previous = self._writes.get(key)
        operation = "create" if previous is not None and previous.operation == "create" else "set"
        self._writes[key] = DocumentWrite(operation, key, document)

    async def delete(self, collection: str, document_id: str) -> None:
        self.ensure_open()
        key = DocumentKey(collection, document_id)
        if await self.get(collection, document_id) is None:
            raise RecordNotFoundError(f"document was not found: {collection}/{document_id}")
        previous = self._writes.get(key)
        self._overlay[key] = _DELETED
        if previous is not None and previous.operation == "create":
            self._writes.pop(key)
        else:
            self._writes[key] = DocumentWrite("delete", key)

    async def commit(self) -> None:
        self.ensure_open()
        await self._backend.atomic_commit(
            reads=tuple(
                ReadExpectation(key, data) for key, data in self._original_reads.items()
            ),
            queries=tuple(self._query_expectations.values()),
            writes=tuple(self._writes.values()),
        )
        self._open = False

    async def rollback(self) -> None:
        self.ensure_open()
        self._open = False


def _matches(document: Mapping[str, object], filters: tuple[QueryFilter, ...]) -> bool:
    for item in filters:
        if item.operator == "==":
            if document.get(item.field) != item.value:
                return False
        elif item.operator == "in":
            if document.get(item.field) not in item.value:
                return False
        else:  # pragma: no cover - all repository queries are declared below this layer
            raise ValueError(f"unsupported in-memory query operator: {item.operator}")
    return True


__all__ = ["FirestoreDocumentSession"]
