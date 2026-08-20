"""Source 변경 이벤트를 Control 로 넘기는 실물 sink.

Agent 2 는 ``SourceChangeSink.persist(change)`` 만 안다. 그 뒤에서 무슨 일이
일어나는지는 모른다. 여기서 Control 의 idempotent 등록으로 잇는다
(docs/INTEGRATION.md 6절, Master Spec 21).

``register_source_change`` 가 내부에서 idempotency 판정, AnalysisJob 생성,
Cloud Tasks enqueue, 관측 이벤트 발생을 모두 수행한다. 그래서 이 sink 는
아무것도 더 하지 않는다 — 큐를 따로 건드리면 중복 enqueue 가 되고, 여기서
다시 로그를 남기면 같은 사건이 두 번 기록된다.
"""

from __future__ import annotations

from iprisk_contracts import SourceChange

from ip_risk_agent.application.public_facade import ControlPlaneFacade


class ControlSourceChangeSink:
    """``SourceChangeSink`` Protocol 의 운영 구현."""

    def __init__(self, facade: ControlPlaneFacade) -> None:
        self._facade = facade

    async def persist(self, change: SourceChange) -> None:
        await self._facade.register_source_change(change)


__all__ = ["ControlSourceChangeSink"]
