"""분석 워커 프로세스 진입점.

실행:

    uvicorn ip_risk_agent.worker:app

Master Spec 21 은 Control 과 분석 사이에 Cloud Tasks 를 둔다. 이 프로세스가
그 큐의 소비자다.

큐는 content-free ``change_event_id`` 하나만 넘기는데 파이프라인의 다음 단계인
``SourceAdapter.fetch_snapshot(change)`` 는 ``SourceChange`` 전체를 요구한다.
그 간극은 Integration 소유 relay 저장소가 메운다. 왜 이 방식이 경계를 지키는지,
더 깔끔한 대안이 무엇인지는 ``composition/gcp/relay.py`` 에 적어 두었다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI, HTTPException, status
from iprisk_contracts import SourceChange
from iprisk_contracts.common import SourceType
from pydantic import BaseModel, ConfigDict

from ip_risk_agent.composition import AnalysisPipeline, Container, build_container
from ip_risk_agent.composition.pipeline import SourceAdapterLike


class ChangeEventTask(BaseModel):
    """Cloud Tasks 가 보내는 본문. content-free ID 하나뿐이다."""

    model_config = ConfigDict(extra="forbid")

    change_event_id: str


def create_worker_app(
    env: Mapping[str, str] | None = None,
    *,
    container: Container | None = None,
    adapters: Mapping[SourceType, SourceAdapterLike] | None = None,
) -> FastAPI:
    """분석 워커 애플리케이션.

    ``adapters`` 는 provider 별 ``SourceAdapter`` 다. 실제 provider client 는
    자격증명을 요구하므로 기본값은 비어 있다. 어댑터가 없는 source_type 의
    작업은 성공으로 위장하지 않고 실패로 남는다.
    """
    resolved = container or build_container(env if env is not None else os.environ)
    resolved_adapters = dict(adapters or {})
    pipeline = AnalysisPipeline(
        resolved.facade,
        adapters=resolved_adapters,
        intelligence=resolved.intelligence,
    )
    relay = resolved.source_ports.change_relay

    app = FastAPI(title="IP Risk Agent Worker", version="0.0.0")
    app.state.container = resolved
    app.state.pipeline = pipeline

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "control_backend": resolved.backend,
            "queue": resolved.queue_backend,
            "intelligence": (
                "enabled" if resolved.intelligence_enabled else "disabled"
            ),
            "adapters": sorted(
                source_type.value for source_type in resolved_adapters
            ),
        }

    def _result(outcome) -> dict[str, object]:
        return {
            "change_event_id": outcome.change_event_id,
            "claimed": outcome.claimed,
            "gate_approved": outcome.gate_approved,
            "results_accepted": outcome.results_accepted,
            "skipped_reason": outcome.skipped_reason,
        }

    @app.post("/internal/analysis/run", tags=["internal"])
    async def run_analysis(change: SourceChange) -> dict[str, object]:
        """``SourceChange`` 본문을 직접 받아 실행한다.

        relay 가 없거나 큐를 쓰지 않는 구성에서 쓴다. 내부 전용 경로다.
        """
        return _result(await pipeline.run(change))

    @app.post("/internal/analysis/dispatch", tags=["internal"])
    async def dispatch_analysis(task: ChangeEventTask) -> dict[str, object]:
        """Cloud Tasks 가 호출하는 경로. ID 로 ``SourceChange`` 를 되찾아 실행한다.

        배포에서는 ingress 에서 차단하고 Cloud Tasks 서비스 계정만 호출할 수
        있게 해야 한다 (Master Spec 40/48).
        """
        change = await relay.resolve(task.change_event_id)
        if change is None:
            # 없는 것을 성공으로 처리하면 변경이 조용히 사라진다. 큐가 재시도할
            # 수 있도록 실패로 알린다.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="change event is not available for dispatch",
            )
        return _result(await pipeline.run(change))

    return app


app: FastAPI = create_worker_app()

__all__ = ["ChangeEventTask", "app", "create_worker_app"]
