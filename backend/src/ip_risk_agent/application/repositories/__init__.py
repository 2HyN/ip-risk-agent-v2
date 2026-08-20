"""Public persistence-neutral repository contracts and in-memory implementation."""

from .errors import (
    ConcurrencyConflictError,
    RecordNotFoundError,
    RepositoryError,
    TransactionClosedError,
    UniqueConstraintViolation,
)
from .in_memory import InMemoryControlStore, InMemoryControlUnitOfWork
from .protocols import (
    AnalysisJobRepository,
    ArtifactRepository,
    AuditRepository,
    ChangeEventRepository,
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    MembershipRepository,
    MountRepository,
    NotificationRepository,
    RiskRepository,
    SourceMetadataRepository,
    UserRepository,
    WorkspaceRepository,
)

__all__ = [
    "AnalysisJobRepository",
    "ArtifactRepository",
    "AuditRepository",
    "ChangeEventRepository",
    "ConcurrencyConflictError",
    "ControlUnitOfWork",
    "ControlUnitOfWorkFactory",
    "InMemoryControlStore",
    "InMemoryControlUnitOfWork",
    "MembershipRepository",
    "MountRepository",
    "NotificationRepository",
    "RecordNotFoundError",
    "RepositoryError",
    "RiskRepository",
    "SourceMetadataRepository",
    "TransactionClosedError",
    "UniqueConstraintViolation",
    "UserRepository",
    "WorkspaceRepository",
]
