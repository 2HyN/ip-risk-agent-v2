"""외부 사실 변화를 촉발하는 것 (§7.6 · 결함 24).

§1.2 (A) 의 가운데 줄이 이 제품이 파는 것이다 — **"우리는 가만있었는데 위험이 생겼다."**
의존성은 그대로인데 그 패키지가 라이선스를 바꾼 경우이고, Redis · Elastic · MongoDB ·
HashiCorp 가 실제로 한 일이다.

그런데 분석은 **변경 이벤트에서만** 시작했다. `requirements.txt` 를 여섯 달 안 건드리면
그 안의 패키지가 MIT 에서 BUSL-1.1 로 바뀌어도 몰랐다. 재료는 다 있고 방아쇠만 없었다.
"""

from __future__ import annotations

import inspect

from ip_risk_agent.composition.scheduler_routes import (
    SchedulerOperations,
    create_scheduler_router,
)
from ip_risk_agent.gcp_contract import SCHEDULER_JOBS


def test_the_trigger_exists_at_all() -> None:
    """이것이 §1.2 (A) 를 실제로 성립시키는 유일한 작업이다. 없으면 그 논거는 말뿐이다."""
    assert "revalidate_licenses" in SchedulerOperations.__protocol_attrs__  # type: ignore[attr-defined]


def test_the_route_is_wired() -> None:
    class _Operations:
        async def renew_drive_watches(self, cursor, limit): ...
        async def reconcile_drive(self, cursor, limit): ...
        async def cleanup_expired(self, cursor, limit): ...
        async def refresh_source_health(self, cursor, limit): ...
        async def revalidate_licenses(self, cursor, limit): ...

    async def _auth(_request): ...

    router = create_scheduler_router(authenticator=_auth, operations=_Operations())
    paths = {route.path for route in router.routes}
    assert "/internal/scheduler/license-revalidation" in paths


def test_the_scheduled_job_is_declared_in_the_deployment_contract() -> None:
    """라우트만 있고 예약 작업이 없으면 아무도 부르지 않는다."""
    import yaml
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    jobs = yaml.safe_load((root / "deploy" / "scheduler-jobs.yaml").read_text("utf-8"))
    names = [job["name"] for job in jobs["jobs"]]
    assert "ip-risk-agent-v2-license-revalidation" in names
    assert names == list(SCHEDULER_JOBS), "계약과 배포 파일이 갈라지면 배포가 막힌다"

    entry = next(
        job for job in jobs["jobs"] if job["name"] == "ip-risk-agent-v2-license-revalidation"
    )
    assert entry["path"] == "/internal/scheduler/license-revalidation"


def test_the_sweep_does_not_touch_the_file() -> None:
    """파일이 아니라 **패키지 메타데이터**가 대상이다.

    파일은 그대로이므로 ``analysis_input_checksum`` 도 그대로이고, 그래서 §7.4 가
    원인을 **"외부 사실"** 로 정확히 귀속할 수 있다 — 입력이 같은데 결과가 달라진
    것이 그 뜻이다. 파일을 건드려 촉발하면 그 귀속이 무너진다.

    그래서 재평가는 **이미 있는 변경 이벤트**를 다시 돌린다. 새 이벤트를 만들지 않는다.
    """
    from ip_risk_agent.application.public_facade.service import ControlPlaneFacade

    source = inspect.getsource(ControlPlaneFacade.revalidate_mount_licenses)
    assert "request_reanalysis" in source
    assert "change_events.add" not in source
    assert "SourceChange(" not in source


def test_truncation_is_reported() -> None:
    """조용히 자르면 "전부 다시 봤다" 로 읽힌다 (§9.1 과 같은 이유다)."""
    from ip_risk_agent.application.public_facade.service import ControlPlaneFacade

    source = inspect.getsource(ControlPlaneFacade.revalidate_mount_licenses)
    assert "license_revalidation_truncated" in source
    assert "return requested, remaining" in source
