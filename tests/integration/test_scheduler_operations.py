from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from iprisk_contracts import (
    MountRef,
    ReconcileResult,
    SourceHealth,
    SourceHealthStatus,
    SourceType,
)

from ip_risk_agent.composition.scheduler_operations import (
    ProductionSchedulerOperations,
)
from ip_risk_agent.gcp.operational_firestore import (
    DEVICE_CHALLENGES,
    OAUTH_STATES,
    PENDING_CONNECTIONS,
    OperationalDocument,
)


NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


class PageStore:
    def __init__(self, records=()) -> None:
        self.records = tuple(records)

    async def page(self, *, cursor, limit):
        assert cursor is None
        return self.records[:limit], None


class MaintenanceStore:
    def __init__(self, pages) -> None:
        self.pages = pages
        self.deleted = []

    async def page(self, collection, *, cursor, limit):
        assert cursor is None
        return tuple(self.pages.get(collection, ()))[:limit], None

    async def delete(self, collection, document_id):
        self.deleted.append((collection, document_id))


class DriveAdapter:
    source_type = SourceType.GOOGLE_DRIVE

    def __init__(self) -> None:
        self.renewed = []
        self.reconciled = []

    async def renew_watch(self, mount, **kwargs):
        self.renewed.append((mount.mount_id, kwargs))
        return True

    async def reconcile(self, mount, cursor):
        self.reconciled.append((mount.mount_id, cursor))
        if cursor is None:
            return ReconcileResult(changes=[], next_cursor="page-2", has_more=True)
        return ReconcileResult(changes=[], next_cursor="committed", has_more=False)

    async def health(self, _mount):
        return SourceHealth(
            status=SourceHealthStatus.HEALTHY,
            checked_at=NOW,
            safe_metadata={},
        )


class HealthAdapter:
    def __init__(self, source_type) -> None:
        self.source_type = source_type

    async def health(self, _mount):
        return SourceHealth(
            status=SourceHealthStatus.HEALTHY,
            checked_at=NOW,
            safe_metadata={},
        )


class Control:
    def __init__(self) -> None:
        self.types = {
            "drive-mount": SourceType.GOOGLE_DRIVE,
            "github-mount": SourceType.GITHUB,
            "local-mount": SourceType.LOCAL,
        }
        self.health = []
        self.revalidated = []

    async def get_mount_ref(self, mount_id):
        return MountRef(
            risk_workspace_id="vws-1",
            mount_id=mount_id,
            source_workspace_id=f"source-{mount_id}",
            source_type=self.types[mount_id],
        )

    async def record_source_health(self, mount_id, health):
        self.health.append((mount_id, health.status))

    async def revalidate_mount_licenses(self, mount_id, *, limit=200):
        self.revalidated.append(mount_id)
        return 2, 0


class Sink:
    async def persist(self, _change):
        return None


def _operations(*, maintenance=None):
    drive = DriveAdapter()
    control = Control()
    operations = ProductionSchedulerOperations(
        maintenance_store=maintenance or MaintenanceStore({}),
        drive_tracking_store=PageStore([SimpleNamespace(mount_id="drive-mount")]),
        github_tracking_store=PageStore([SimpleNamespace(mount_id="github-mount")]),
        local_runtime_store=PageStore(
            [SimpleNamespace(mount_handle="local-mount")]
        ),
        drive_adapter=drive,
        github_adapter=HealthAdapter(SourceType.GITHUB),
        local_adapter=HealthAdapter(SourceType.LOCAL),
        control_facade=control,
        change_sink=Sink(),
        drive_webhook_url="https://api.example.com/webhooks/google-drive",
        drive_channel_token="opaque-channel-token",
        clock=lambda: NOW,
    )
    return operations, drive, control


def test_production_scheduler_renews_reconciles_and_refreshes_all_sources() -> None:
    async def scenario() -> None:
        operations, drive, control = _operations()
        renewal = await operations.renew_drive_watches(None, 100)
        reconciliation = await operations.reconcile_drive(None, 100)
        health = await operations.refresh_source_health(None, 100)

        assert renewal.model_dump() == {
            "processed": 1,
            "failed": 0,
            "next_cursor": None,
        }
        assert reconciliation.processed == 1
        assert drive.reconciled == [
            ("drive-mount", None),
            ("drive-mount", "page-2"),
        ]
        assert health.processed == 3
        assert {item[0] for item in control.health} == {
            "drive-mount",
            "github-mount",
            "local-mount",
        }
        assert drive.renewed[0][1]["channel_token"] == "opaque-channel-token"

    asyncio.run(scenario())


def test_expired_cleanup_preserves_active_pending_connection_records() -> None:
    expired = NOW - timedelta(minutes=1)
    maintenance = MaintenanceStore(
        {
            PENDING_CONNECTIONS: (
                OperationalDocument(
                    "pending-stale",
                    {"status": "PENDING", "expires_at": expired},
                ),
                OperationalDocument(
                    "pending-active",
                    {"status": "ACTIVE", "expires_at": expired},
                ),
            ),
            OAUTH_STATES: (
                OperationalDocument("oauth-stale", {"expires_at": expired}),
            ),
            DEVICE_CHALLENGES: (
                OperationalDocument("challenge-stale", {"expires_at": expired}),
            ),
        }
    )

    async def scenario() -> None:
        operations, _, _ = _operations(maintenance=maintenance)
        result = await operations.cleanup_expired(None, 100)
        assert result.processed == 4
        assert result.failed == 0
        assert set(maintenance.deleted) == {
            (PENDING_CONNECTIONS, "pending-stale"),
            (OAUTH_STATES, "oauth-stale"),
            (DEVICE_CHALLENGES, "challenge-stale"),
        }

    asyncio.run(scenario())
