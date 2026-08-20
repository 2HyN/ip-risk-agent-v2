"""분석 파이프라인 실행체.

Master Spec 21 의 고정 순서를 그대로 코드로 옮긴 것이다. Source Plane 과
Intelligence Plane 사이에 직접 호출 경로가 없다는 규칙을 지키기 위해, 이
모듈만이 양쪽을 안다.

지켜야 하는 불변조건 (docs/INTEGRATION.md 2절, Master Spec 17/18):

- provider 실패를 빈 성공이나 "Risk 없음" 으로 바꾸지 않는다.
- Gate 가 승인하지 않으면 Analyzer 를 호출하지 않는다.
- ``SourceSnapshot`` 은 transient 다. 이 함수 밖으로 내보내지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from iprisk_contracts import SourceChange, SourceSnapshot
from iprisk_contracts.common import SourceType

from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    SourceScopeInput,
)


class SourceAdapterLike(Protocol):
    """Agent 2 의 ``SourceAdapter`` 중 이 파이프라인이 쓰는 부분."""

    async def fetch_snapshot(self, change: SourceChange) -> SourceSnapshot: ...


class IntelligenceLike(Protocol):
    """Agent 3 의 ``IntelligenceFacade`` 중 이 파이프라인이 쓰는 부분."""

    def supports(self, artifact: object) -> bool: ...

    async def analyze(self, artifact: object) -> list: ...


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """무엇이 일어났는지 호출부가 알 수 있게 남긴다."""

    change_event_id: str | None
    claimed: bool
    gate_approved: bool
    results_accepted: int
    skipped_reason: str | None = None


class AnalysisPipeline:
    """SourceChange 하나를 Risk 까지 밀어 넣는다."""

    def __init__(
        self,
        facade: ControlPlaneFacade,
        *,
        adapters: Mapping[SourceType, SourceAdapterLike],
        intelligence: IntelligenceLike | None = None,
    ) -> None:
        self._facade = facade
        self._adapters = dict(adapters)
        self._intelligence = intelligence

    async def run(self, change: SourceChange) -> PipelineOutcome:
        registration = await self._facade.register_source_change(change)
        change_event_id = registration.change_event_id

        claim = await self._facade.claim_analysis(change_event_id)
        if claim is None:
            # 이미 다른 워커가 가져갔다. 중복 처리하지 않는다.
            return PipelineOutcome(change_event_id, False, False, 0, "already_claimed")

        adapter = self._adapters.get(change.source_type)
        if adapter is None:
            # 어댑터가 없는 것은 provider 장애가 아니라 배포 구성 결함이다.
            # 그래도 성공으로 바꾸지 않고 실패로 남겨 Risk 를 보존한다.
            await self._facade.fail_analysis(
                change_event_id, failure_safe="PROVIDER_UNAVAILABLE"
            )
            return PipelineOutcome(
                change_event_id, True, False, 0, "no_adapter_for_source_type"
            )

        try:
            snapshot = await adapter.fetch_snapshot(change)
        except Exception:
            await self._facade.fail_analysis(
                change_event_id, failure_safe="PROVIDER_UNAVAILABLE"
            )
            raise

        gate = await self._facade.build_analysis_artifact(
            snapshot,
            claim.analysis_job_id,
            source_scope=SourceScopeInput(in_scope=True),
        )
        if not gate.approved:
            return PipelineOutcome(
                change_event_id, True, False, 0, "gate_rejected"
            )

        if self._intelligence is None:
            # 분석 경로가 구성되지 않았다. Gate 는 통과했으므로 실패가 아니지만,
            # 결과가 없으므로 Control 이 기존 Risk 를 해소하지 않는다.
            return PipelineOutcome(
                change_event_id, True, True, 0, "intelligence_not_configured"
            )

        artifact = gate.analysis_artifact
        if not self._intelligence.supports(artifact):
            return PipelineOutcome(
                change_event_id, True, True, 0, "no_analyzer_supports_artifact"
            )

        accepted = 0
        for result in await self._intelligence.analyze(artifact):
            await self._facade.accept_analysis_result(result)
            accepted += 1
        return PipelineOutcome(change_event_id, True, True, accepted)


__all__ = ["AnalysisPipeline", "PipelineOutcome", "SourceAdapterLike"]
