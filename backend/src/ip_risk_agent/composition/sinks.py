"""Source 변경 이벤트를 Control 로 넘기는 실물 sink.

Agent 2 는 ``SourceChangeSink.persist(change)`` 만 안다. 그 뒤에서 무슨 일이
일어나는지는 모른다. 여기서 Control 의 idempotent 등록으로 잇는다
(docs/INTEGRATION.md 6절, Master Spec 21).

``register_source_change`` 가 내부에서 idempotency 판정, AnalysisJob 생성,
Cloud Tasks enqueue, 관측 이벤트 발생을 모두 수행한다. 그래서 이 sink 는 큐를
따로 건드리지 않는다 — 건드리면 중복 enqueue 가 된다.

relay 만 추가로 적는다. 큐는 content-free ID 만 넘기는데 워커는
``SourceChange`` 전체가 필요해서다. 자세한 이유는 ``gcp/relay.py`` 참고.
"""

from __future__ import annotations

from iprisk_contracts import SourceChange

from ip_risk_agent.application.public_facade import ControlPlaneFacade

from .gcp.relay import ChangeRelayStore


class ControlSourceChangeSink:
    """``SourceChangeSink`` Protocol 의 운영 구현."""

    def __init__(
        self,
        facade: ControlPlaneFacade,
        *,
        relay: ChangeRelayStore | None = None,
    ) -> None:
        self._facade = facade
        self._relay = relay

    async def persist(self, change: SourceChange) -> None:
        receipt = await self._facade.register_source_change(change)
        if self._relay is not None:
            # 등록이 성공한 뒤에만 적는다. 등록이 실패했는데 relay 에만 남으면
            # 큐에 없는 유령 항목이 생긴다.
            await self._relay.remember(receipt.change_event_id, change)


__all__ = ["ControlSourceChangeSink"]
