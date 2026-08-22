"""Production analyzer-set and result-set completeness boundary."""

from __future__ import annotations

from iprisk_contracts import AnalysisArtifact, AnalysisResult, AnalysisType


class AnalyzerCompletenessError(RuntimeError):
    pass


class CompleteIntelligenceFacade:
    """Reject silent analyzer omission before Control can leave a job running."""

    def __init__(
        self,
        delegate,
        *,
        configured_analysis_types: tuple[AnalysisType, ...],
        active_analysis_types: tuple[AnalysisType, ...],
    ) -> None:
        configured = frozenset(configured_analysis_types)
        active = frozenset(active_analysis_types)
        if not configured or configured != active:
            raise AnalyzerCompletenessError(
                "Control requested analyzer set must exactly match active analyzers"
            )
        self._delegate = delegate
        self._active = active

    @property
    def risk_explainer(self):
        """감싼 쪽의 설명기를 그대로 내보낸다.

        이 경계는 **분석기 집합**의 완결성만 본다. 설명기는 판정이 아니어서 여기서
        다루지 않는데, 그렇다고 가려 버리면 조립이 그것을 찾지 못한다. 실제로
        배포된 Risk 에 설명과 권고가 하나도 붙지 않았다 — 설명기가 없는 것으로
        처리되어 실패조차 남지 않았다.
        """
        return getattr(self._delegate, "risk_explainer", None)

    async def analyze(self, artifact: AnalysisArtifact) -> list[AnalysisResult]:
        requested = frozenset(artifact.requested_analyzers)
        if (
            not requested
            or len(artifact.requested_analyzers) != len(requested)
            or not requested.issubset(self._active)
        ):
            raise AnalyzerCompletenessError(
                "artifact requested analyzers must be a unique active subset"
            )
        results = list(await self._delegate.analyze(artifact))
        result_types = [result.analysis_type for result in results]
        if len(result_types) != len(set(result_types)) or frozenset(result_types) != requested:
            raise AnalyzerCompletenessError(
                "analysis results are missing, duplicated, or unexpected"
            )
        for result in results:
            if (
                result.analysis_job_id != artifact.analysis_job_id
                or result.artifact_id != artifact.artifact_id
                or result.revision != artifact.revision
            ):
                raise AnalyzerCompletenessError(
                    "analysis result identity does not match the gated artifact"
                )
        return results

    def supports(self, artifact: AnalysisArtifact) -> bool:
        requested = frozenset(artifact.requested_analyzers)
        return bool(requested) and requested.issubset(self._active)


__all__ = ["AnalyzerCompletenessError", "CompleteIntelligenceFacade"]
