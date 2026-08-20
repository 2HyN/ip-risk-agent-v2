"""분석 워커 프로세스 진입점.

실행:

    uvicorn ip_risk_agent.worker:app

Master Spec 21 은 Control 과 분석 사이에 Cloud Tasks 를 둔다. 이 프로세스가
그 큐의 소비자다.

---------------------------------------------------------------------------
알려진 계약 공백 — Integration 이 임의로 메우지 않고 기록만 한다
---------------------------------------------------------------------------
`TaskEnqueuer.enqueue_change(change_event_id: str)` 는 content-free ID 하나만
넘긴다 (docs/IMPLEMENTATION_STATUS.md 1절). 그런데 파이프라인의 다음 단계인
`SourceAdapter.fetch_snapshot(change)` 는 `SourceChange` 전체를 요구하고,
`ControlPlaneFacade` 의 공개 메서드 중 `change_event_id` 로 `SourceChange` 를
되짚는 것이 없다.

따라서 ID 만으로 워커를 기동하려면 Control 이 조회 메서드를 하나 더 공개해야
한다. 그때까지 이 워커는 `SourceChange` 본문을 직접 받는 경로만 제공한다.
Master Spec 62 에 따라 contract-change request 대상으로 올려야 하는 항목이며,
Integration 이 Control 내부를 우회 조회해 임시로 해결하지 않는다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI
from iprisk_contracts import SourceChange
from iprisk_contracts.common import SourceType

from ip_risk_agent.composition import AnalysisPipeline, Container, build_container
from ip_risk_agent.composition.pipeline import SourceAdapterLike


def create_worker_app(
    env: Mapping[str, str] | None = None,
    *,
    container: Container | None = None,
    adapters: Mapping[SourceType, SourceAdapterLike] | None = None,
) -> FastAPI:
    """분석 워커 애플리케이션.

    `adapters` 는 provider 별 `SourceAdapter` 다. 실제 provider client 는
    자격증명을 요구하므로 기본값은 비어 있다. 어댑터가 없는 source_type 의
    작업은 성공으로 위장하지 않고 실패로 남는다.
    """
    resolved = container or build_container(env if env is not None else os.environ)
    pipeline = AnalysisPipeline(
        resolved.facade,
        adapters=adapters or {},
        intelligence=resolved.intelligence,
    )

    app = FastAPI(title="IP Risk Agent Worker", version="0.0.0")
    app.state.container = resolved
    app.state.pipeline = pipeline

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "control_backend": resolved.backend,
            "intelligence": (
                "enabled" if resolved.intelligence_enabled else "disabled"
            ),
            "adapters": sorted(
                source_type.value for source_type in (adapters or {})
            ),
        }

    @app.post("/internal/analysis/run", tags=["internal"])
    async def run_analysis(change: SourceChange) -> dict[str, object]:
        """SourceChange 하나를 Risk 까지 밀어 넣는다.

        내부 전용 경로다. 배포에서는 ingress 에서 차단하고 Cloud Tasks
        서비스 계정만 호출할 수 있게 해야 한다 (Master Spec 40/48).
        """
        outcome = await pipeline.run(change)
        return {
            "change_event_id": outcome.change_event_id,
            "claimed": outcome.claimed,
            "gate_approved": outcome.gate_approved,
            "results_accepted": outcome.results_accepted,
            "skipped_reason": outcome.skipped_reason,
        }

    return app


app: FastAPI = create_worker_app()

__all__ = ["app", "create_worker_app"]
