"""Raw-free task enqueue port and deterministic in-memory fake."""

from __future__ import annotations

import asyncio
from typing import Protocol

from ip_risk_agent.core.common import require_non_empty


class TaskEnqueueError(RuntimeError):
    pass


class TaskEnqueuer(Protocol):
    """Enqueue by canonical ID only; implementations must de-duplicate that ID."""

    async def enqueue_change(self, change_event_id: str) -> None: ...


class InMemoryTaskEnqueuer:
    """Idempotent fake whose only accepted payload is a ChangeEvent ID."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending_ids: set[str] = set()
        self._attempts: list[str] = []
        self._failures_remaining = 0

    def fail_next(self, count: int = 1) -> None:
        if count < 1:
            raise ValueError("failure count must be positive")
        self._failures_remaining += count

    async def enqueue_change(self, change_event_id: str) -> None:
        change_event_id = require_non_empty(change_event_id, "queue.change_event_id")
        async with self._lock:
            self._attempts.append(change_event_id)
            if self._failures_remaining:
                self._failures_remaining -= 1
                raise TaskEnqueueError("in-memory enqueue failure")
            self._pending_ids.add(change_event_id)

    @property
    def pending_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending_ids))

    @property
    def attempts(self) -> tuple[str, ...]:
        return tuple(self._attempts)


__all__ = ["InMemoryTaskEnqueuer", "TaskEnqueueError", "TaskEnqueuer"]
