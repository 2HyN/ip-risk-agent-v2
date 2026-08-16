"""Agent 1 canonical Firestore persistence namespace."""

from .backend import FirestoreDocumentBackend, GoogleFirestoreBackend
from .mappers import DocumentMappingError
from .repositories import FirestoreControlUnitOfWork, FirestoreControlUnitOfWorkFactory
from .schema import CANONICAL_COLLECTIONS, REQUIRED_COMPOSITE_INDEXES

__all__ = [
    "CANONICAL_COLLECTIONS",
    "DocumentMappingError",
    "FirestoreControlUnitOfWork",
    "FirestoreControlUnitOfWorkFactory",
    "FirestoreDocumentBackend",
    "GoogleFirestoreBackend",
    "REQUIRED_COMPOSITE_INDEXES",
]

