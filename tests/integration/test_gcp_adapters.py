"""GCP 어댑터 검증.

실제 GCP 를 호출하지 않는다. SDK 자리에 가짜 클라이언트를 넣어 **우리가 짠 로직**
— de-dup 키, 만료 처리, 실패를 성공으로 바꾸지 않기 — 만 확인한다.

SDK 자체의 동작은 우리 책임이 아니다. 우리 책임은 그것을 어떻게 쓰느냐다.
"""

from __future__ import annotations

import json

import pytest

from ip_risk_agent.composition.gcp.queue import CloudTasksEnqueuer
from ip_risk_agent.composition.gcp.relay import InMemoryChangeRelayStore
from ip_risk_agent.composition.gcp.secrets import secret_id_for
from ip_risk_agent.connectors.common.credential_vault import CredentialScope
from iprisk_contracts.common import SourceType

from .test_analysis_pipeline import make_change


class AlreadyExists(Exception):
    """google.api_core.exceptions.AlreadyExists 대역."""


class FakeTasksClient:
    """create_task 만 흉내 낸다. 실제 서비스처럼, 이름이 지정된 작업은
    tombstone(실행 후 재사용 금지)에 걸릴 수 있으므로 이름 지정 자체를
    계약 위반으로 본다."""

    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_task(self, request: dict) -> None:
        self.created.append(request["task"])


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


@pytest.mark.asyncio
async def test_tasks_are_not_named_so_retries_survive_tombstones(
    enqueuer_with_fake,
) -> None:
    """작업 이름을 지정하면 재시도가 조용히 사라진다.

    Cloud Tasks 는 실행이 끝난 이름을 약 1시간 기억(tombstone)한다. 결정적
    이름을 쓰면 실패한 이벤트의 재큐잉이 AlreadyExists 로 버려지는데,
    오류는 어디에도 남지 않는다 — 운영에서 재분석 31건이 그렇게 사라졌다.
    중복 투입의 방어는 클레임 단계(already_claimed)가 한다.
    """
    enqueuer, client = enqueuer_with_fake

    await enqueuer.enqueue_change("change:v1:abc")
    await enqueuer.enqueue_change("change:v1:abc")

    assert len(client.created) == 2
    assert all("name" not in task for task in client.created)


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
