"""SourceChange -> Gate -> Analyzer -> Risk 경로 검증.

Master Spec 21 의 고정 순서를 지키는지, 그리고 실패를 성공으로 바꾸지 않는지를
본다. 한 Plane 안에서는 확인할 수 없는 경계다.

준비 단계를 in-memory 저장소에 직접 써 넣지 않고 **실제 HTTP API 로** 만든다.
그래야 Control 의 canonical 생성 경로와 Source 라우터의 등록 경로가 정말
맞물리는지 함께 검증된다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from iprisk_contracts import SourceChange
from iprisk_contracts.common import SourceType

from ip_risk_agent.composition import AnalysisPipeline, create_app

from .conftest import build_test_container, login

# 손으로 만든 페이로드는 Frozen Contract 와 어긋나기 쉽다. 저장소의 정식
# fixture 를 기준으로 삼고 필요한 필드만 바꾼다.
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "shared"
    / "contracts"
    / "fixtures"
    / "source-change-local.json"
)


def make_change(**overrides) -> SourceChange:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.update(overrides)
    return SourceChange.model_validate(payload)


class ExplodingAdapter:
    """provider 장애 재현용."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_snapshot(self, change: SourceChange):
        self.calls += 1
        raise RuntimeError("provider is down")


def provision_local_mount(client: TestClient) -> dict[str, str]:
    """로그인 -> VWS 생성 -> 기기 등록 -> Mount 등록까지 실제 API 로 진행한다."""
    _user_id, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}

    created = client.post(
        "/api/v1/workspaces",
        json={"name": "Integration Workspace"},
        headers=headers,
    )
    assert created.status_code in {200, 201}, created.text
    workspace_id = created.json()["id"]

    device = client.post(
        "/desktop/devices/register",
        json={"device_id": "device-7", "device_label": "integration-laptop"},
    )
    assert device.status_code == 200, device.text

    mount = client.post(
        "/desktop/mounts/register",
        json={"risk_workspace_id": workspace_id, "device_id": "device-7"},
    )
    assert mount.status_code == 200, mount.text
    body = mount.json()
    return {
        "risk_workspace_id": workspace_id,
        "mount_id": body["server_mount_id"],
        "source_workspace_id": body["source_workspace_id"],
    }


@pytest.fixture
def provisioned():
    """컨테이너와 그 위에 만들어진 실제 VWS/Mount 를 함께 돌려준다."""
    container = build_test_container()
    with TestClient(create_app(container=container)) as client:
        ids = provision_local_mount(client)
    return container, ids


@pytest.mark.asyncio
async def test_missing_adapter_is_recorded_as_failure_not_success(provisioned) -> None:
    """어댑터가 없으면 조용히 성공시키지 않는다.

    provider/system failure 를 "Risk 없음" 으로 바꾸지 않는 것이 전역 불변조건이다
    (README 11, Master Spec 17).
    """
    container, ids = provisioned
    pipeline = AnalysisPipeline(container.facade, adapters={})

    outcome = await pipeline.run(make_change(**ids))

    assert outcome.claimed is True
    assert outcome.gate_approved is False
    assert outcome.results_accepted == 0
    assert outcome.skipped_reason == "no_adapter_for_source_type"


@pytest.mark.asyncio
async def test_provider_failure_propagates_and_does_not_swallow(provisioned) -> None:
    """스냅샷 실패는 삼키지 않고 올린다. 실패 기록은 Control 이 남긴다."""
    container, ids = provisioned
    adapter = ExplodingAdapter()
    pipeline = AnalysisPipeline(
        container.facade, adapters={SourceType.LOCAL: adapter}
    )

    with pytest.raises(RuntimeError):
        await pipeline.run(make_change(**ids))

    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_same_change_maps_to_one_stable_event_id(provisioned) -> None:
    """같은 변경은 몇 번을 넣어도 같은 ChangeEvent 로 접힌다.

    idempotency 의 실제 보장은 "한 번만 점유된다"가 아니라 "같은 사건은 하나의
    content-free ID 로 수렴한다"이다. 실패한 작업의 재점유는 오히려 정상이다
    (`ControlPlaneFacadeConfig.retry_failed_events` 기본값 True).
    """
    container, ids = provisioned
    pipeline = AnalysisPipeline(container.facade, adapters={})

    change = make_change(**ids)
    first = await pipeline.run(change)
    second = await pipeline.run(change)

    assert first.change_event_id == second.change_event_id
    # 실패로 기록된 뒤이므로 재시도가 허용된다. 성공으로 위장되지 않았음을
    # 함께 확인한다.
    assert first.skipped_reason == "no_adapter_for_source_type"
    assert second.skipped_reason == "no_adapter_for_source_type"
    assert (first.results_accepted, second.results_accepted) == (0, 0)


@pytest.mark.asyncio
async def test_second_claim_is_skipped_while_the_first_is_in_flight(
    provisioned,
) -> None:
    """아직 처리 중인 작업은 다른 워커가 가져가지 못한다."""
    container, ids = provisioned
    facade = container.facade

    registration = await facade.register_source_change(make_change(**ids))
    first = await facade.claim_analysis(registration.change_event_id)
    second = await facade.claim_analysis(registration.change_event_id)

    assert first is not None
    assert second is None


def test_desktop_event_reaches_control_through_the_source_sink() -> None:
    """Electron -> /desktop/events -> ControlSourceChangeSink -> Control 등록.

    Source Plane 이 Control 내부를 모른 채로도 변경이 canonical 저장소에
    도달하는지 본다. 이 경로가 끊기면 감시가 조용히 멈춘다.
    """
    container = build_test_container()
    with TestClient(create_app(container=container)) as client:
        ids = provision_local_mount(client)

        # 실제 Electron 흐름과 같은 순서다. 내용은 먼저 staging 에 올리고,
        # 이벤트에는 그 opaque 참조만 실린다 (원본 경로/내용은 싣지 않는다).
        staged = client.post(
            "/desktop/staging",
            json={"mount_id": ids["mount_id"], "content": "print('hello')"},
        )
        assert staged.status_code == 200, staged.text
        staging_object_name = staged.json()["object_name"]

        response = client.post(
            "/desktop/events",
            json={
                "risk_workspace_id": ids["risk_workspace_id"],
                "mount_id": ids["mount_id"],
                "source_workspace_id": ids["source_workspace_id"],
                "device_id": "device-7",
                "relative_path": "src/parser.py",
                "change_type": "CREATE",
                "revision": "sha256-1",
                "staging_object_name": staging_object_name,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["event_id"]
