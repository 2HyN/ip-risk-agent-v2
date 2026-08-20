"""Google Drive push notification 라우터. Agent 2 Spec 37번(/webhooks/google-drive).

GitHub과 달리 payload에 실제 변경 내용이 없다 — "채널 X에 변경 있음"이라는
신호만 헤더로 온다. 그래서 이 라우터는 새 파싱 로직이 아니라, Phase C에서
이미 만든 DriveAdapter.reconcile()을 호출해서 실제 변경사항을 받아오는
배선(wiring)에 가깝다.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, HTTPException, Request

from iprisk_contracts.common import MountRef
from iprisk_contracts.source_adapter import ReconcileResult

from ..common.change_sink import SourceChangeSink
from .mount_resolver import DriveChannelMountResolver


class DriveReconciler(Protocol):
    async def reconcile(self, mount: MountRef, cursor: str | None) -> ReconcileResult: ...


def create_drive_webhook_router(
    *,
    adapter: DriveReconciler,
    channel_resolver: DriveChannelMountResolver,
    channel_token: str,
    change_sink: SourceChangeSink,
) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/google-drive")
    async def handle_drive_notification(request: Request) -> dict:
        token = request.headers.get("X-Goog-Channel-Token")
        if token != channel_token:
            raise HTTPException(status_code=401, detail="invalid channel token")

        resource_state = request.headers.get("X-Goog-Resource-State", "")
        if resource_state == "sync":
            return {"status": "ok", "reason": "sync_ack"}

        channel_id = request.headers.get("X-Goog-Channel-ID", "")
        mount = await channel_resolver.resolve_mount(channel_id)
        if mount is None:
            return {"status": "ok", "reason": "unknown_channel"}

        total_changes = 0
        cursor: str | None = None
        has_more = True
        while has_more:
            result = await adapter.reconcile(mount, cursor)
            for change in result.changes:
                await change_sink.persist(change)
            total_changes += len(result.changes)
            has_more = result.has_more
            cursor = result.next_cursor

        return {"status": "ok", "changes_persisted": total_changes}

    return router
