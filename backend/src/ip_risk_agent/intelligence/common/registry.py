"""요청된 Analyzer 를 골라 실행한다.

하나의 artifact 에 PATENT 와 LICENSE 가 함께 요청될 수 있으므로 결과는 목록이다
(Agent 3 Spec 3). 한 Analyzer 가 실패해도 다른 하나는 결과를 내야 한다.
"""

from __future__ import annotations

import asyncio

from iprisk_contracts import AnalysisArtifact, AnalysisResult
from iprisk_contracts.common import AnalysisType

from .analyzer import Analyzer


class AnalyzerRegistry:
    """analysis type 하나당 Analyzer 하나."""

    def __init__(self, analyzers: list[Analyzer] | None = None) -> None:
        self._analyzers: dict[AnalysisType, Analyzer] = {}
        for analyzer in analyzers or []:
            self.register(analyzer)

    def register(self, analyzer: Analyzer) -> None:
        existing = self._analyzers.get(analyzer.analysis_type)
        if existing is not None:
            raise ValueError(
                f"{analyzer.analysis_type.value} analyzer is already registered"
            )
        self._analyzers[analyzer.analysis_type] = analyzer

    def get(self, analysis_type: AnalysisType) -> Analyzer | None:
        return self._analyzers.get(analysis_type)

    @property
    def analysis_types(self) -> tuple[AnalysisType, ...]:
        return tuple(sorted(self._analyzers, key=lambda item: item.value))

    def selected(self, artifact: AnalysisArtifact) -> list[Analyzer]:
        """요청되었고 등록되어 있으며 이 artifact 를 다룰 수 있는 것만.

        요청 순서를 유지한다. 결과 순서가 실행마다 달라지면 통합 쪽에서 비교가 어렵다.
        """
        chosen: list[Analyzer] = []
        for analysis_type in artifact.requested_analyzers:
            analyzer = self._analyzers.get(analysis_type)
            if analyzer is not None and analyzer.supports(artifact):
                chosen.append(analyzer)
        return chosen

    async def analyze(self, artifact: AnalysisArtifact) -> list[AnalysisResult]:
        """선택된 Analyzer 를 동시에 돌린다.

        예외는 삼키지 않는다. Analyzer 는 provider 실패를 결과로 표현할 책임이 있고,
        그러지 못한 예외는 결함이므로 Integration 까지 올라가야 한다.
        """
        analyzers = self.selected(artifact)
        if not analyzers:
            return []
        return list(
            await asyncio.gather(*(analyzer.analyze(artifact) for analyzer in analyzers))
        )
