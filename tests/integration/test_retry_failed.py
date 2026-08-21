"""실패한 분석 재실행 라우트 검증.

큐 재시도가 소진되면 작업은 폐기되지만 이벤트(FAILED)와 원본(relay)은
남는다. 이 라우트가 그 둘을 이어 되살린다 — 없으면 사용자는 폴더 재선택
이라는 우회로 같은 fingerprint 를 재주입해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ip_risk_agent.application.process_change.models import ChangeEventStatus
from ip_risk_agent.composition.retry_failed import create_retry_failed_router


@dataclass
class Event:
    id: str
    status: ChangeEventStatus


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


def build_client(events, relay, sink, authz_calls=None):
    async def authz(request, resource_id: str) -> None:
        if authz_calls is not None:
            authz_calls.append(resource_id)

    uow = FakeUow(change_events=FakeChangeEvents(events))
    app = FastAPI()
    app.include_router(
        create_retry_failed_router(
            unit_of_work_factory=lambda: uow,
            change_relay=relay,
            change_sink=sink,
            authz_dependency=authz,
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
