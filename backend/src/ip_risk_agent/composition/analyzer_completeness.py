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

    async def analyze(self, artifact: AnalysisArtifact) -> list[AnalysisResult]:
        requested = frozenset(artifact.requested_analyzers)
        if len(artifact.requested_analyzers) != len(requested) or requested != self._active:
            raise AnalyzerCompletenessError(
                "artifact requested analyzer set does not match active analyzers"
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
        return frozenset(artifact.requested_analyzers) == self._active


__all__ = ["AnalyzerCompletenessError", "CompleteIntelligenceFacade"]
