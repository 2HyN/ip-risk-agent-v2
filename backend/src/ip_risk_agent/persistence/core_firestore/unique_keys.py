"""Deterministic unique-key sentinels stored inside canonical collections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ip_risk_agent.application.repositories import UniqueConstraintViolation
from ip_risk_agent.core.common import stable_key

from .mappers import Document, DocumentMappingError
from .schema import DOCUMENT_SCHEMA_VERSION
from .session import FirestoreDocumentSession


def unique_document_id(namespace: str, components: Iterable[str]) -> str:
    return stable_key(f"unique-{namespace}", components)


async def claim_unique_key(
    session: FirestoreDocumentSession,
    *,
    collection: str,
    namespace: str,
    components: tuple[str, ...],
    owner_document_id: str,
) -> None:
    document_id = unique_document_id(namespace, components)
    existing = await session.get(collection, document_id)
    if existing is not None:
        owner = unique_key_owner(existing, namespace=namespace)
        if owner != owner_document_id:
            raise UniqueConstraintViolation(f"unique key already exists: {namespace}")
        return
    await session.create(
        collection,
        document_id,
        unique_key_document(namespace, owner_document_id),
    )


async def resolve_unique_key(
    session: FirestoreDocumentSession,
    *,
    collection: str,
    namespace: str,
    components: tuple[str, ...],
) -> str | None:
    document = await session.get(
        collection, unique_document_id(namespace, components)
    )
    return None if document is None else unique_key_owner(document, namespace=namespace)


async def release_unique_key(
    session: FirestoreDocumentSession,
    *,
    collection: str,
    namespace: str,
    components: tuple[str, ...],
    owner_document_id: str,
) -> None:
    document_id = unique_document_id(namespace, components)
    document = await session.get(collection, document_id)
    if document is None:
        raise DocumentMappingError(f"missing unique-key sentinel: {namespace}")
    if unique_key_owner(document, namespace=namespace) != owner_document_id:
        raise DocumentMappingError(f"unique-key sentinel owner mismatch: {namespace}")
    await session.delete(collection, document_id)


def unique_key_document(namespace: str, owner_document_id: str) -> Document:
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "record_kind": "unique_key",
        "namespace": namespace,
        "owner_document_id": owner_document_id,
    }


def unique_key_owner(document: Mapping[str, object], *, namespace: str) -> str:
    expected = {"schema_version", "record_kind", "namespace", "owner_document_id"}
    if set(document) != expected:
        raise DocumentMappingError(f"invalid unique-key document shape: {namespace}")
    if document["schema_version"] != DOCUMENT_SCHEMA_VERSION:
        raise DocumentMappingError(f"unsupported unique-key schema version: {namespace}")
    if document["record_kind"] != "unique_key" or document["namespace"] != namespace:
        raise DocumentMappingError(f"unique-key namespace mismatch: {namespace}")
    owner = document["owner_document_id"]
    if not isinstance(owner, str) or not owner:
        raise DocumentMappingError(f"invalid unique-key owner: {namespace}")
    return owner


__all__ = [
    "claim_unique_key",
    "release_unique_key",
    "resolve_unique_key",
    "unique_document_id",
    "unique_key_document",
    "unique_key_owner",
]
