"""실패한 분석 재실행 라우트 검증.

큐 재시도가 소진되면 작업은 폐기되지만 이벤트(FAILED)와 원본(relay)은
남는다. 이 라우트가 그 둘을 이어 되살린다 — 없으면 사용자는 폴더 재선택
이라는 우회로 같은 fingerprint 를 재주입해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ip_risk_agent.application.process_change.models import ChangeEventStatus
from ip_risk_agent.composition.retry_failed import create_retry_failed_router


NOW = datetime.now(UTC)


@dataclass
class Event:
    id: str
    status: ChangeEventStatus
    updated_at: datetime = NOW


@dataclass
class FakeChangeEvents:
    events: list[Event]

    async def list_for_workspace(self, risk_workspace_id: str):
        return tuple(self.events)


@dataclass
class FakeUow:
    change_events: FakeChangeEvents

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@dataclass
class FakeRelay:
    changes: dict = field(default_factory=dict)

    async def resolve(self, change_event_id: str):
        return self.changes.get(change_event_id)


@dataclass
class FakeSink:
    persisted: list = field(default_factory=list)
    fail_for: set = field(default_factory=set)

    async def persist(self, change) -> None:
        if change in self.fail_for:
            raise RuntimeError("control rejected")
        self.persisted.append(change)


def build_client(events, relay, sink, authz_calls=None, failed_events=None):
    async def authz(request, resource_id: str) -> None:
        if authz_calls is not None:
            authz_calls.append(resource_id)

    async def fail_analysis(change_event_id: str, *, failure_safe: str) -> None:
        if failed_events is not None:
            failed_events.append((change_event_id, failure_safe))

    uow = FakeUow(change_events=FakeChangeEvents(events))
    app = FastAPI()
    app.include_router(
        create_retry_failed_router(
            unit_of_work_factory=lambda: uow,
            change_relay=relay,
            change_sink=sink,
            authz_dependency=authz,
            fail_analysis=fail_analysis,
        )
    )
    return TestClient(app)


def test_failed_events_are_requeued_and_done_ones_are_left_alone() -> None:
    relay = FakeRelay({"evt-failed": "change-1"})
    sink = FakeSink()
    client = build_client(
        [
            Event("evt-failed", ChangeEventStatus.FAILED),
            Event("evt-done", ChangeEventStatus.DONE),
            Event("evt-pending", ChangeEventStatus.PENDING),
        ],
        relay,
        sink,
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert body == {"requeued": 1, "expired": 0}
    # DONE/PENDING 은 건드리지 않는다. 성공분을 다시 돌리면 비용만 는다.
    assert sink.persisted == ["change-1"]


def test_expired_relay_entries_are_counted_not_hidden() -> None:
    """7일이 지난 실패는 살릴 수 없다. 조용히 빼면 "전부 다시 돌렸다"로
    읽히므로 개수로 알린다."""
    sink = FakeSink()
    client = build_client(
        [
            Event("evt-old", ChangeEventStatus.FAILED),
            Event("evt-recent", ChangeEventStatus.FAILED),
        ],
        FakeRelay({"evt-recent": "change-2"}),
        sink,
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert body == {"requeued": 1, "expired": 1}


def test_one_rejected_persist_does_not_block_the_rest() -> None:
    sink = FakeSink(fail_for={"change-broken"})
    client = build_client(
        [
            Event("evt-1", ChangeEventStatus.FAILED),
            Event("evt-2", ChangeEventStatus.FAILED),
        ],
        FakeRelay({"evt-1": "change-broken", "evt-2": "change-ok"}),
        sink,
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert body["requeued"] == 1
    assert sink.persisted == ["change-ok"]


def test_the_route_is_behind_workspace_authz() -> None:
    calls: list = []
    client = build_client([], FakeRelay(), FakeSink(), authz_calls=calls)

    client.post("/api/v1/workspaces/vws-1/analyses/retry-failed")

    assert calls == ["vws-1"]


def test_stale_processing_zombies_are_failed_then_requeued() -> None:
    """워커가 분석 도중 죽으면 이벤트는 PROCESSING 에 갇힌다.

    그 좀비는 FAILED 필터·재선택·큐 재시도 어디에도 걸리지 않는다 —
    프롬프트 누락 사고에서 특허 배치가 실제로 그렇게 갇혔다.
    """
    failed_calls: list = []
    sink = FakeSink()
    client = build_client(
        [
            Event(
                "evt-zombie",
                ChangeEventStatus.PROCESSING,
                updated_at=NOW - timedelta(hours=1),
            ),
        ],
        FakeRelay({"evt-zombie": "change-z"}),
        sink,
        failed_events=failed_calls,
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert failed_calls == [("evt-zombie", "STUCK_PROCESSING")]
    assert body["requeued"] == 1
    assert sink.persisted == ["change-z"]


def test_recent_processing_is_left_running() -> None:
    """방금 시작한 분석을 죽이면 안 된다. 오래 머문 것만 좀비로 본다."""
    failed_calls: list = []
    sink = FakeSink()
    client = build_client(
        [Event("evt-live", ChangeEventStatus.PROCESSING, updated_at=NOW)],
        FakeRelay({"evt-live": "change-l"}),
        sink,
        failed_events=failed_calls,
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert failed_calls == []
    assert body == {"requeued": 0, "expired": 0}
    assert sink.persisted == []


def _real_event(event_id: str, status: ChangeEventStatus):
    from iprisk_contracts.common import ChangeType, SourceType

    from ip_risk_agent.application.process_change.models import ChangeEvent

    return ChangeEvent(
        id=event_id,
        event_fingerprint=f"fp-{event_id}",
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        source_workspace_id="sws-1",
        source_artifact_id=f"src-{event_id}",
        source_type=SourceType.GOOGLE_DRIVE,
        change_type=ChangeType.CREATE,
        revision="r1",
        previous_revision=None,
        observed_at=NOW,
        status=status,
        attempts=1,
        created_at=NOW,
        updated_at=NOW,
        artifact_id=f"art-{event_id}",
    )


def _real_job(event_id: str, status):
    from iprisk_contracts.common import AnalysisType

    from ip_risk_agent.application.analysis_jobs.models import AnalysisJob

    return AnalysisJob(
        id=f"job-{event_id}",
        change_event_id=event_id,
        artifact_id=f"art-{event_id}",
        revision="r1",
        requested_analysis_types=(AnalysisType.PATENT,),
        status=status,
        created_at=NOW,
        # 종결 상태(SUCCEEDED/INCONCLUSIVE)는 시작·완료 시각을 요구한다.
        started_at=NOW,
        completed_at=NOW,
    )


class StatefulUow:
    """save 를 실제로 반영하는 uow 대역."""

    def __init__(self, events, jobs_by_event):
        self._events = {e.id: e for e in events}
        self._jobs = dict(jobs_by_event)
        self.change_events = self
        self.analysis_jobs = self

    async def list_for_workspace(self, risk_workspace_id):
        return tuple(self._events.values())

    async def list_for_change(self, change_event_id):
        return tuple(self._jobs.get(change_event_id, ()))

    async def save(self, record):
        # ChangeEvent 와 AnalysisJob 을 한 대역이 받는다. id 모양으로 구분.
        if hasattr(record, "event_fingerprint"):
            self._events[record.id] = record
        else:
            self._jobs[record.change_event_id] = (record,)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class RecordingEnqueuer:
    def __init__(self):
        self.enqueued: list[str] = []

    async def enqueue_change(self, change_event_id: str) -> None:
        self.enqueued.append(change_event_id)


def build_inconclusive_client(events, jobs_by_event, relay, enqueuer):
    async def authz(request, resource_id: str) -> None:
        pass

    async def fail_analysis(change_event_id: str, *, failure_safe: str) -> None:
        pass

    uow = StatefulUow(events, jobs_by_event)
    app = FastAPI()
    app.include_router(
        create_retry_failed_router(
            unit_of_work_factory=lambda: uow,
            change_relay=relay,
            change_sink=FakeSink(),
            authz_dependency=authz,
            fail_analysis=fail_analysis,
            task_enqueuer=enqueuer,
        )
    )
    return TestClient(app), uow


def test_inconclusive_executions_are_revived_but_succeeded_are_not() -> None:
    """미결은 권위 있는 결론이 아니다 — 수집 결함을 고친 뒤 다시 돌 수
    있어야 한다. 진짜 성공은 건드리면 사실이 뒤집힌다."""
    from ip_risk_agent.application.analysis_jobs.models import AnalysisJobStatus
    from ip_risk_agent.application.process_change.models import (
        ChangeEventStatus as CES,
    )

    events = [
        _real_event("evt-incl", CES.DONE),
        _real_event("evt-good", CES.DONE),
    ]
    jobs = {
        "evt-incl": (_real_job("evt-incl", AnalysisJobStatus.INCONCLUSIVE),),
        "evt-good": (_real_job("evt-good", AnalysisJobStatus.SUCCEEDED),),
    }
    enqueuer = RecordingEnqueuer()
    client, uow = build_inconclusive_client(
        events, jobs, FakeRelay({"evt-incl": "change-i", "evt-good": "change-g"}), enqueuer
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert body["requeued"] == 1
    assert enqueuer.enqueued == ["evt-incl"]
    assert uow._events["evt-incl"].status.value == "PENDING"
    assert uow._jobs["evt-incl"][0].status is AnalysisJobStatus.QUEUED
    # 성공한 실행은 그대로다.
    assert uow._events["evt-good"].status.value == "DONE"


def test_inconclusive_without_relay_counts_as_expired() -> None:
    from ip_risk_agent.application.analysis_jobs.models import AnalysisJobStatus
    from ip_risk_agent.application.process_change.models import (
        ChangeEventStatus as CES,
    )

    enqueuer = RecordingEnqueuer()
    client, uow = build_inconclusive_client(
        [_real_event("evt-old", CES.DONE)],
        {"evt-old": (_real_job("evt-old", AnalysisJobStatus.INCONCLUSIVE),)},
        FakeRelay(),
        enqueuer,
    )

    body = client.post("/api/v1/workspaces/vws-1/analyses/retry-failed").json()

    assert body == {"requeued": 0, "expired": 1}
    assert enqueuer.enqueued == []
    # 원본을 못 구하면 상태도 건드리지 않는다.
    assert uow._events["evt-old"].status.value == "DONE"
