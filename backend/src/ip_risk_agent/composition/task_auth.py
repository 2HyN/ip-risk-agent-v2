"""Worker task identity boundary; production OIDC implementation arrives in Phase 6."""

from __future__ import annotations

import secrets
from typing import Protocol

from fastapi import HTTPException, Request


class TaskAuthenticator(Protocol):
    async def __call__(self, request: Request) -> None: ...


class DenyTaskAuthenticator:
    async def __call__(self, request: Request) -> None:
        raise HTTPException(status_code=401, detail="internal task identity is not configured")


class StaticBearerTaskAuthenticator:
    """Explicit test/local adapter; never accepted by production container policy."""

    def __init__(self, token: str) -> None:
        if len(token) < 32:
            raise ValueError("local task token must contain at least 32 characters")
        self._token = token

    async def __call__(self, request: Request) -> None:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, value = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not secrets.compare_digest(value, self._token)
        ):
            raise HTTPException(status_code=401, detail="invalid internal task identity")


__all__ = [
    "DenyTaskAuthenticator",
    "StaticBearerTaskAuthenticator",
    "TaskAuthenticator",
]
