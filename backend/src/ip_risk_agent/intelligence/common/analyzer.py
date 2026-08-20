"""Analyzer 규약과 결과 조립기.

``AnalysisResult`` 는 Risk 상태가 아니라 분석 보고서다. Control Plane 은
``SUCCEEDED + COMPLETE`` 일 때만 기존 Risk 를 해소하므로, coverage 를 낙관적으로
매기면 provider 장애가 "위험 해소"로 둔갑한다. 그 실수를 코드로 막는 것이
:class:`ResultBuilder` 의 역할이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from iprisk_contracts import AnalysisArtifact, AnalysisResult
from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisStatus,
    AnalysisType,
    AnalysisVersions,
    LicenseCandidate,
    PatentCandidate,
    ProviderFailure,
)

from .errors import ProviderFailureError
from .evidence import EvidenceLedger


def utcnow() -> datetime:
    """Contract 가 timezone-aware datetime 을 요구한다."""
    return datetime.now(UTC)


@runtime_checkable
class Analyzer(Protocol):
    """Registry 가 기대하는 최소 규약."""

    analysis_type: AnalysisType

    def supports(self, artifact: AnalysisArtifact) -> bool:
        """이 artifact 를 다룰 수 있는지. 요청 여부와는 별개다."""
        ...

    async def analyze(self, artifact: AnalysisArtifact) -> AnalysisResult:
        ...


class ResultBuilder:
    """분석 한 건의 수명주기를 들고 있다가 Contract 를 조립한다.

    started_at 은 생성 시각으로 고정한다. Analyzer 가 직접 시각을 다루면
    빠뜨리거나 순서가 뒤집힌다.
    """

    def __init__(
        self,
        artifact: AnalysisArtifact,
        analysis_type: AnalysisType,
        analyzer_version: str,
        *,
        ledger: EvidenceLedger | None = None,
    ) -> None:
        self.artifact = artifact
        self.analysis_type = analysis_type
        self.analyzer_version = analyzer_version
        self.ledger = ledger if ledger is not None else EvidenceLedger()
        self.failures: list[ProviderFailure] = []
        self._started_at = utcnow()

    # ------------------------------------------------------------- 실패 기록

    def record_failure(self, failure: ProviderFailureError | ProviderFailure) -> None:
        """provider 실패를 남긴다. 여기 쌓인 것은 결과에 반드시 실린다."""
        self.failures.append(
            failure.as_contract() if isinstance(failure, ProviderFailureError) else failure
        )

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)

    # ------------------------------------------------------------- 결과 조립

    def build(
        self,
        status: AnalysisStatus,
        coverage: AnalysisCoverage,
        *,
        candidates: list[PatentCandidate | LicenseCandidate] | None = None,
        model_id: str | None = None,
        prompt_version: str | None = None,
        policy_version: str | None = None,
        rag_corpus_version: str | None = None,
    ) -> AnalysisResult:
        selected = list(candidates or [])

        # Contract 검증기가 같은 규칙을 다시 확인하지만, 여기서 먼저 막아야
        # 어느 Analyzer 가 잘못 판단했는지 알 수 있다.
        if status is not AnalysisStatus.SUCCEEDED and coverage is AnalysisCoverage.COMPLETE:
            raise ValueError(
                f"{status.value} result cannot claim COMPLETE coverage"
            )
        if status is not AnalysisStatus.SUCCEEDED and selected:
            raise ValueError(
                f"{status.value} result must not report candidates"
            )
        for candidate in selected:
            self.ledger.require(candidate.evidence_ids)

        return AnalysisResult(
            contract_version="1",
            analysis_job_id=self.artifact.analysis_job_id,
            artifact_id=self.artifact.artifact_id,
            revision=self.artifact.revision,
            analysis_type=self.analysis_type,
            status=status,
            coverage=coverage,
            candidates=selected,
            evidence=self.ledger.items(),
            provider_failures=list(self.failures),
            versions=AnalysisVersions(
                analyzer_version=self.analyzer_version,
                model_id=model_id,
                prompt_version=prompt_version,
                policy_version=policy_version,
                rag_corpus_version=rag_corpus_version,
            ),
            started_at=self._started_at,
            completed_at=utcnow(),
        )

    def succeeded(
        self,
        candidates: list[PatentCandidate | LicenseCandidate],
        *,
        coverage: AnalysisCoverage | None = None,
        **versions: str | None,
    ) -> AnalysisResult:
        """정상 완료. coverage 를 넘기지 않으면 실패 유무로 정한다.

        후보 0건도 성공이다. 다만 provider 가 하나라도 실패했다면 COMPLETE 가 아니다.
        """
        if coverage is None:
            coverage = (
                AnalysisCoverage.PARTIAL if self.has_failures else AnalysisCoverage.COMPLETE
            )
        return self.build(
            AnalysisStatus.SUCCEEDED, coverage, candidates=candidates, **versions
        )

    def failed(self, **versions: str | None) -> AnalysisResult:
        """필수 단계가 실패. 이 결과로는 기존 Risk 를 해소할 수 없다."""
        coverage = AnalysisCoverage.PARTIAL if len(self.ledger) else AnalysisCoverage.NONE
        return self.build(AnalysisStatus.FAILED, coverage, **versions)

    def inconclusive(self, **versions: str | None) -> AnalysisResult:
        """파이프라인은 정상이었으나 판단할 근거가 부족했다."""
        return self.build(AnalysisStatus.INCONCLUSIVE, AnalysisCoverage.NONE, **versions)

    def skipped(self, **versions: str | None) -> AnalysisResult:
        """분석 대상이 아니다. 실패와 구분해야 한다."""
        return self.build(AnalysisStatus.SKIPPED, AnalysisCoverage.NONE, **versions)
