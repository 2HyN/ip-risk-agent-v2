"""Production scheduler operations over bounded durable source state."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from iprisk_contracts import SourceType

from ip_risk_agent.composition.source_registration import PendingConnectionStatus
from ip_risk_agent.gcp.operational_firestore import (
    DEVICE_CHALLENGES,
    OAUTH_STATES,
    PENDING_CONNECTIONS,
    FirestoreMaintenanceStore,
)

from .scheduler_routes import MaintenanceResult


class ProductionSchedulerOperations:
    """Retry-safe maintenance using existing adapters and canonical facade."""

    def __init__(
        self,
        *,
        maintenance_store: FirestoreMaintenanceStore,
        drive_tracking_store,
        github_tracking_store,
        local_runtime_store,
        drive_adapter,
        github_adapter,
        local_adapter,
        control_facade,
        change_sink,
        drive_webhook_url: str,
        drive_channel_token: str,
        clock,
    ) -> None:
        self._maintenance = maintenance_store
        self._drive_tracking = drive_tracking_store
        self._github_tracking = github_tracking_store
        self._local_runtime = local_runtime_store
        self._adapters = {
            SourceType.GOOGLE_DRIVE: drive_adapter,
            SourceType.GITHUB: github_adapter,
            SourceType.LOCAL: local_adapter,
        }
        self._drive = drive_adapter
        self._control = control_facade
        self._sink = change_sink
        self._drive_webhook_url = drive_webhook_url
        self._drive_channel_token = drive_channel_token
        self._clock = clock

    async def renew_drive_watches(
        self,
        cursor: str | None,
        limit: int,
    ) -> MaintenanceResult:
        records, next_cursor = await _page_sources(
            "drive-watch-renewal",
            (("drive", self._drive_tracking),),
            cursor,
            limit,
        )
        processed = failed = 0
        now = self._clock()
        for _source, scope in records:
            try:
                mount = await self._control.get_mount_ref(scope.mount_id)
                await self._drive.renew_watch(
                    mount,
                    address=self._drive_webhook_url,
                    channel_token=self._drive_channel_token,
                    now=now,
                )
                processed += 1
            except Exception:
                failed += 1
        return MaintenanceResult(
            processed=processed,
            failed=failed,
            next_cursor=next_cursor,
        )

    async def reconcile_drive(
        self,
        cursor: str | None,
        limit: int,
    ) -> MaintenanceResult:
        records, next_cursor = await _page_sources(
            "drive-reconciliation",
            (("drive", self._drive_tracking),),
            cursor,
            limit,
        )
        processed = failed = 0
        for _source, scope in records:
            try:
                mount = await self._control.get_mount_ref(scope.mount_id)
                page_cursor: str | None = None
                seen_cursors: set[str] = set()
                while True:
                    result = await self._drive.reconcile(mount, page_cursor)
                    for change in result.changes:
                        await self._sink.persist(change)
                    if not result.has_more:
                        break
                    if (
                        result.next_cursor is None
                        or result.next_cursor in seen_cursors
                    ):
                        raise RuntimeError("Drive reconciliation cursor did not advance")
                    seen_cursors.add(result.next_cursor)
                    page_cursor = result.next_cursor
                processed += 1
            except Exception:
                failed += 1
        return MaintenanceResult(
            processed=processed,
            failed=failed,
            next_cursor=next_cursor,
        )

    async def cleanup_expired(
        self,
        cursor: str | None,
        limit: int,
    ) -> MaintenanceResult:
        sources = tuple(
            (collection, _MaintenanceCollection(self._maintenance, collection))
            for collection in (
                PENDING_CONNECTIONS,
                OAUTH_STATES,
                DEVICE_CHALLENGES,
            )
        )
        records, next_cursor = await _page_sources(
            "expired-state-cleanup",
            sources,
            cursor,
            limit,
        )
        processed = failed = 0
        now = self._clock()
        for collection, document in records:
            try:
                if _is_cleanup_candidate(collection, document.data, now):
                    await self._maintenance.delete(collection, document.document_id)
                processed += 1
            except Exception:
                failed += 1
        return MaintenanceResult(
            processed=processed,
            failed=failed,
            next_cursor=next_cursor,
        )

    async def refresh_source_health(
        self,
        cursor: str | None,
        limit: int,
    ) -> MaintenanceResult:
        records, next_cursor = await _page_sources(
            "source-health-refresh",
            (
                (SourceType.GOOGLE_DRIVE.value, self._drive_tracking),
                (SourceType.GITHUB.value, self._github_tracking),
                (SourceType.LOCAL.value, self._local_runtime),
            ),
            cursor,
            limit,
        )
        processed = failed = 0
        for source_value, record in records:
            try:
                source_type = SourceType(source_value)
                mount_id = (
                    record.mount_handle
                    if source_type is SourceType.LOCAL
                    else record.mount_id
                )
                mount = await self._control.get_mount_ref(mount_id)
                if mount.source_type is not source_type:
                    raise RuntimeError("operational source type does not match mount")
                health = await self._adapters[source_type].health(mount)
                await self._control.record_source_health(mount_id, health)
                processed += 1
            except Exception:
                failed += 1
        return MaintenanceResult(
            processed=processed,
            failed=failed,
            next_cursor=next_cursor,
        )


class _MaintenanceCollection:
    def __init__(self, store: FirestoreMaintenanceStore, collection: str) -> None:
        self._store = store
        self._collection = collection

    async def page(self, *, cursor: str | None, limit: int):
        return await self._store.page(
            self._collection,
            cursor=cursor,
            limit=limit,
        )


async def _page_sources(
    operation: str,
    sources: Sequence[tuple[str, Any]],
    cursor: str | None,
    limit: int,
) -> tuple[list[tuple[str, Any]], str | None]:
    source_index, document_cursor = _decode_cursor(operation, cursor)
    if source_index >= len(sources):
        raise HTTPException(status_code=422, detail="invalid scheduler cursor")
    remaining = limit
    records: list[tuple[str, Any]] = []
    while source_index < len(sources) and remaining > 0:
        source_name, store = sources[source_index]
        page, next_document_cursor = await store.page(
            cursor=document_cursor,
            limit=remaining,
        )
        records.extend((source_name, record) for record in page)
        remaining -= len(page)
        if next_document_cursor is not None:
            return records, _encode_cursor(
                operation,
                source_index,
                next_document_cursor,
            )
        source_index += 1
        document_cursor = None
    next_cursor = (
        _encode_cursor(operation, source_index, None)
        if source_index < len(sources)
        else None
    )
    return records, next_cursor


def _is_cleanup_candidate(collection: str, data: dict, now: datetime) -> bool:
    expires_at = data.get("expires_at")
    if not isinstance(expires_at, datetime) or expires_at > now:
        return False
    if collection == PENDING_CONNECTIONS:
        return data.get("status") == PendingConnectionStatus.PENDING.value
    return collection in {OAUTH_STATES, DEVICE_CHALLENGES}


def _encode_cursor(operation: str, source_index: int, document_cursor: str | None) -> str:
    payload = json.dumps(
        {"v": 1, "op": operation, "source": source_index, "after": document_cursor},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(operation: str, cursor: str | None) -> tuple[int, str | None]:
    if cursor is None:
        return 0, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            value.get("v") != 1
            or value.get("op") != operation
            or not isinstance(value.get("source"), int)
            or value["source"] < 0
            or (
                value.get("after") is not None
                and not isinstance(value.get("after"), str)
            )
        ):
            raise ValueError
        return value["source"], value.get("after")
    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise HTTPException(status_code=422, detail="invalid scheduler cursor") from exc


__all__ = ["ProductionSchedulerOperations"]
