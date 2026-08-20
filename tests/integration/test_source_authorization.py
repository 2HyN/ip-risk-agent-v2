"""Source 라우터가 Control RBAC 뒤에 있는지 검증한다.

Agent 2 의 `authz_dependency` 기본값 `allow_all_authz` 는 아무것도 검사하지
않는다 (AGENT_2_DELIVERY 10-1). Integration 이 실제 검사로 바꾸지 않으면
Source 라우터 전체가 무인증으로 열린다.

이 파일은 그 상태가 다시 생기지 않게 잠그는 회귀 테스트다. 한 Plane 안에서는
확인할 수 없는 경계라서 Integration 소유다 (Master Spec 55).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import login

VALID_EVENT = {
    "risk_workspace_id": "vws-1",
    "mount_id": "mount-1",
    "source_workspace_id": "sw-1",
    "device_id": "device-1",
    "relative_path": "docs/plan.md",
    "change_type": "UPDATE",
}

# 본문은 스키마를 만족해야 한다. 그래야 401 이 "검증 실패"가 아니라
# "인증 실패"임이 분명해진다.
UNAUTHENTICATED_CASES = [
    ("/desktop/devices/register", {"device_id": "device-1", "device_label": "laptop"}),
    (
        "/desktop/mounts/register",
        {"risk_workspace_id": "vws-1", "device_id": "device-1"},
    ),
    ("/desktop/staging", {"mount_id": "mount-1", "content": "hello"}),
    ("/desktop/events", VALID_EVENT),
]


@pytest.mark.parametrize("path,body", UNAUTHENTICATED_CASES)
def test_source_routes_reject_anonymous_callers(
    client: TestClient, path: str, body: dict
) -> None:
    response = client.post(path, json=body)
    assert response.status_code == 401, (
        f"{path} 이 인증 없이 통과했다 — allow_all_authz 가 남아 있는지 확인할 것"
    )


def test_authenticated_caller_passes_authz_and_reaches_the_handler(
    client: TestClient,
) -> None:
    """인증만 통과하면 authz 단계를 지나 실제 핸들러에 도달해야 한다."""
    login(client)
    response = client.post(
        "/desktop/devices/register",
        json={"device_id": "device-1", "device_label": "laptop"},
    )
    # 401 이 아니면 authz 를 통과한 것이다. 기기 등록은 VWS 스코프가 없으므로
    # 로그인만으로 성공한다.
    assert response.status_code == 200


def test_mount_registration_requires_workspace_membership(client: TestClient) -> None:
    """로그인했더라도 남의(또는 없는) VWS 에 Mount 를 붙일 수 없다."""
    login(client)
    client.post(
        "/desktop/devices/register",
        json={"device_id": "device-1", "device_label": "laptop"},
    )
    response = client.post(
        "/desktop/mounts/register",
        json={"risk_workspace_id": "vws-does-not-exist", "device_id": "device-1"},
    )
    # 존재 여부를 알려주지 않고 권한 없음으로 닫는다.
    assert response.status_code == 403


def test_drive_connection_start_is_workspace_scoped() -> None:
    """provider 라우터도 같은 규칙을 따른다."""
    from ip_risk_agent.composition import create_app

    from .conftest import build_test_container

    container = build_test_container(
        {
            "GOOGLE_DRIVE_CLIENT_ID": "drive-client",
            "GOOGLE_DRIVE_CLIENT_SECRET": "drive-secret",
            "GOOGLE_DRIVE_REDIRECT_URI": "http://testserver/oauth/drive",
        }
    )
    with TestClient(create_app(container=container)) as client:
        anonymous = client.post(
            "/api/v1/source-connections/google-drive/start",
            json={"risk_workspace_id": "vws-1"},
        )
        assert anonymous.status_code == 401

        login(client)
        denied = client.post(
            "/api/v1/source-connections/google-drive/start",
            json={"risk_workspace_id": "vws-does-not-exist"},
        )
        assert denied.status_code == 403
