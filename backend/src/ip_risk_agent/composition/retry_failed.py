"""실패한 분석을 화면에서 명시적으로 되살린다.

큐의 재시도가 소진되면 작업은 폐기되지만, 이벤트는 Control 에 FAILED 로
남고 원본 SourceChange 는 relay 에 7일간 보관된다. 즉 되살릴 재료는 다
있는데 그것을 묶는 손잡이가 없어서, 사용자는 폴더를 다시 선택하는 우회로
같은 fingerprint 를 재주입해야 했다 — 배포로 고치는 유형의 장애 뒤에는
항상 이 우회가 필요했다.

이 라우트는 그 재료를 그대로 잇는다. FAILED 이벤트를 나열하고, relay 에서
원본을 복원해 평소의 sink 로 다시 넣는다. 이후는 Control 의
FAILED_REQUEUED 경로가 처리하므로 — 성공분(DONE)은 건너뛰고 실패분만
재큐잉된다 — 새 상태 전이를 만들지 않는다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ip_risk_agent.application.process_change.models import ChangeEventStatus

logger = logging.getLogger(__name__)


class RetryFailedResponse(BaseModel):
    requeued: int
    # relay 보존(7일)이 지난 실패. 이 버튼으로는 못 살리므로 숨기지 않고
    # 세어서 알린다 — 조용히 빼면 "전부 다시 돌렸다"로 읽힌다.
    expired: int


# 이 시간보다 오래 PROCESSING 에 머문 이벤트는 워커가 도중에 죽은 것으로
# 본다. 정상 분석은 길어야 수 분이다. 너무 짧게 잡으면 진행 중인 분석을
# 죽이고, 안 잡으면 좀비가 영원히 남는다.
STALE_PROCESSING_AFTER = timedelta(minutes=15)


def create_retry_failed_router(
    *,
    unit_of_work_factory,
    change_relay,
    change_sink,
    authz_dependency,
    fail_analysis=None,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/workspaces/{vws_id}/analyses/retry-failed",
        response_model=RetryFailedResponse,
    )
    async def retry_failed(vws_id: str, request: Request) -> RetryFailedResponse:
        await authz_dependency(request, vws_id)

        async with unit_of_work_factory() as uow:
            events = await uow.change_events.list_for_workspace(vws_id)
        failed = [
            event for event in events if event.status is ChangeEventStatus.FAILED
        ]

        # 워커가 분석 도중 죽으면 이벤트는 FAILED 가 아니라 PROCESSING 에
        # 갇힌다. 그 좀비는 재시도·재선택·이 버튼의 FAILED 필터 어디에도
        # 걸리지 않으므로, 오래 머문 것을 FAILED 로 내려 되살린다.
        if fail_analysis is not None:
            stale_before = datetime.now(UTC) - STALE_PROCESSING_AFTER
            for event in events:
                if event.status is not ChangeEventStatus.PROCESSING:
                    continue
                if event.updated_at > stale_before:
                    continue  # 아직 진행 중일 수 있다. 죽이지 않는다.
                try:
                    await fail_analysis(event.id, failure_safe="STUCK_PROCESSING")
                except Exception:
                    # 그 사이 상태가 바뀌었을 수 있다. 이 건만 넘어간다.
                    logger.exception(
                        "retry-failed: could not fail a stuck event (event=%s)",
                        event.id,
                    )
                    continue
                failed.append(event)

        requeued = 0
        expired = 0
        for event in failed:
            change = await change_relay.resolve(event.id)
            if change is None:
                expired += 1
                continue
            try:
                await change_sink.persist(change)
            except Exception:
                # 한 건의 실패가 나머지 재투입을 막으면 안 된다. 이 건은
                # 다음 번 버튼에서 다시 시도된다.
                logger.exception(
                    "retry-failed: persist failed (event=%s)", event.id
                )
                continue
            requeued += 1

        return RetryFailedResponse(requeued=requeued, expired=expired)

    return router


__all__ = ["RetryFailedResponse", "create_retry_failed_router"]
