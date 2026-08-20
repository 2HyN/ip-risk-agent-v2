"""GCP 어댑터 검증.

실제 GCP 를 호출하지 않는다. SDK 자리에 가짜 클라이언트를 넣어 **우리가 짠 로직**
— de-dup 키, 만료 처리, 실패를 성공으로 바꾸지 않기 — 만 확인한다.

SDK 자체의 동작은 우리 책임이 아니다. 우리 책임은 그것을 어떻게 쓰느냐다.
"""

from __future__ import annotations

import json

import pytest

from ip_risk_agent.composition.gcp.queue import CloudTasksEnqueuer, task_name_for
from ip_risk_agent.composition.gcp.relay import InMemoryChangeRelayStore
from ip_risk_agent.composition.gcp.secrets import secret_id_for
from ip_risk_agent.connectors.common.credential_vault import CredentialScope
from iprisk_contracts.common import SourceType

from .test_analysis_pipeline import make_change


class AlreadyExists(Exception):
    """google.api_core.exceptions.AlreadyExists 대역."""


class FakeTasksClient:
    """create_task 만 흉내 낸다. 같은 이름이면 AlreadyExists 를 던진다."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self._names: set[str] = set()

    def create_task(self, request: dict) -> None:
        task = request["task"]
        name = task["name"]
        if name in self._names:
            raise AlreadyExists(name)
        self._names.add(name)
        self.created.append(task)


@pytest.fixture
def enqueuer_with_fake(monkeypatch):
    client = FakeTasksClient()
    enqueuer = CloudTasksEnqueuer(
        project_id="proj",
        location="asia-northeast3",
        queue="analysis-queue",
        worker_url="https://worker.invalid/internal/analysis/dispatch",
        service_account_email="tasks@proj.iam.gserviceaccount.com",
        client=client,
    )
    # SDK 예외 모듈을 대역으로 바꾼다.
    import google.api_core.exceptions as exceptions

    monkeypatch.setattr(exceptions, "AlreadyExists", AlreadyExists, raising=False)
    return enqueuer, client


def test_task_name_is_deterministic_and_safe() -> None:
    """같은 ID 는 같은 이름이어야 de-dup 이 성립한다."""
    change_id = "change:v1:84bfc388a7de2a7f33c949f1ad3cebba"
    first = task_name_for(change_id)
    assert first == task_name_for(change_id)
    # canonical ID 의 ':' 가 남으면 Cloud Tasks 가 거부한다.
    assert ":" not in first
    assert first != task_name_for(change_id + "x")


@pytest.mark.asyncio
async def test_duplicate_enqueue_is_absorbed(enqueuer_with_fake) -> None:
    """같은 change_event_id 를 두 번 넣어도 task 는 하나다."""
    enqueuer, client = enqueuer_with_fake

    await enqueuer.enqueue_change("change:v1:abc")
    await enqueuer.enqueue_change("change:v1:abc")

    assert len(client.created) == 1


@pytest.mark.asyncio
async def test_enqueued_payload_carries_only_the_id(enqueuer_with_fake) -> None:
    """큐에 원본이나 자격증명이 실리면 안 된다."""
    enqueuer, client = enqueuer_with_fake

    await enqueuer.enqueue_change("change:v1:abc")

    body = json.loads(client.created[0]["http_request"]["body"])
    assert body == {"change_event_id": "change:v1:abc"}


@pytest.mark.asyncio
async def test_enqueue_failure_is_not_swallowed(monkeypatch) -> None:
    """큐 적재 실패를 성공으로 바꾸면 변경이 조용히 사라진다."""

    class ExplodingClient:
        def create_task(self, request: dict) -> None:
            raise RuntimeError("queue is unreachable")

    from ip_risk_agent.application.process_change.queue import TaskEnqueueError

    enqueuer = CloudTasksEnqueuer(
        project_id="proj",
        location="asia-northeast3",
        queue="analysis-queue",
        worker_url="https://worker.invalid/dispatch",
        service_account_email="tasks@proj.iam.gserviceaccount.com",
        client=ExplodingClient(),
    )
    with pytest.raises(TaskEnqueueError):
        await enqueuer.enqueue_change("change:v1:abc")


def test_secret_id_is_stable_and_name_safe() -> None:
    """재시도가 새 secret 을 만들지 않으려면 이름이 안정적이어야 한다."""
    scope = CredentialScope(
        provider=SourceType.GOOGLE_DRIVE,
        connection_id="conn:1",
        secret_name="oauth-token",
    )
    first = secret_id_for(scope)
    assert first == secret_id_for(scope)
    # Secret Manager 이름 규칙: 영숫자·하이픈·언더스코어만.
    assert all(ch.isalnum() or ch in "-_" for ch in first)
    assert len(first) <= 255


@pytest.mark.asyncio
async def test_change_relay_roundtrips_the_contract() -> None:
    """relay 가 되돌려준 값이 원래 Contract 와 같아야 한다."""
    relay = InMemoryChangeRelayStore()
    change = make_change()

    await relay.remember("evt-1", change)
    restored = await relay.resolve("evt-1")

    assert restored == change


@pytest.mark.asyncio
async def test_change_relay_returns_none_for_unknown_id() -> None:
    """없는 것을 빈 값으로 위장하지 않는다. 호출부가 실패로 처리해야 한다."""
    relay = InMemoryChangeRelayStore()
    assert await relay.resolve("missing") is None
