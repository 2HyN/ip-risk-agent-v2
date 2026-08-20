from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from ip_risk_agent.composition.scheduler_routes import (
    MaintenanceResult,
    create_scheduler_router,
)


class BearerAuth:
    async def __call__(self, request: Request) -> None:
        if request.headers.get("Authorization") != "Bearer scheduler":
            raise HTTPException(status_code=401)


class Operations:
    def __init__(self) -> None:
        self.calls = []

    async def _run(self, name, cursor, limit):
        self.calls.append((name, cursor, limit))
        return MaintenanceResult(processed=limit, failed=0, next_cursor="next")

    async def renew_drive_watches(self, cursor, limit):
        return await self._run("watch", cursor, limit)

    async def reconcile_drive(self, cursor, limit):
        return await self._run("reconcile", cursor, limit)

    async def cleanup_expired(self, cursor, limit):
        return await self._run("cleanup", cursor, limit)

    async def refresh_source_health(self, cursor, limit):
        return await self._run("health", cursor, limit)


def test_scheduler_routes_require_identity_and_bound_the_batch() -> None:
    operations = Operations()
    app = FastAPI()
    app.include_router(create_scheduler_router(authenticator=BearerAuth(), operations=operations))
    client = TestClient(app)

    assert client.post(
        "/internal/scheduler/drive-watch-renewal", json={}
    ).status_code == 401
    response = client.post(
        "/internal/scheduler/drive-watch-renewal",
        headers={"Authorization": "Bearer scheduler"},
        json={"cursor": "cursor-1", "limit": 25},
    )
    assert response.status_code == 200
    assert response.json() == {"processed": 25, "failed": 0, "next_cursor": "next"}
    assert operations.calls == [("watch", "cursor-1", 25)]
    assert client.post(
        "/internal/scheduler/drive-watch-renewal",
        headers={"Authorization": "Bearer scheduler"},
        json={"limit": 501},
    ).status_code == 422
