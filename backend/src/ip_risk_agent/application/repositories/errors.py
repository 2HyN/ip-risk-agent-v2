"""Persistence-neutral repository errors."""


class RepositoryError(RuntimeError):
    """Base error for Control Plane persistence contracts."""


class RecordNotFoundError(RepositoryError):
    pass


class UniqueConstraintViolation(RepositoryError):
    pass


class ConcurrencyConflictError(RepositoryError):
    pass


class TransactionClosedError(RepositoryError):
    pass
