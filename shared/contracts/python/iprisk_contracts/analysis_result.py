"""Evidence-grounded analyzer output contract, distinct from Risk state."""

from typing import Literal

from pydantic import AwareDatetime, model_validator

from .common import (
    AnalysisCoverage,
    AnalysisStatus,
    AnalysisType,
    AnalysisVersions,
    Evidence,
    LicenseCandidate,
    PatentCandidate,
    ProviderFailure,
    StrictModel,
)


class AnalysisResult(StrictModel):
    contract_version: Literal["1"]
    analysis_job_id: str
    artifact_id: str
    revision: str
    analysis_type: AnalysisType
    status: AnalysisStatus
    coverage: AnalysisCoverage
    candidates: list[PatentCandidate | LicenseCandidate]
    evidence: list[Evidence]
    provider_failures: list[ProviderFailure]
    versions: AnalysisVersions
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_result_invariants(self) -> "AnalysisResult":
        if self.status is not AnalysisStatus.SUCCEEDED and self.coverage is AnalysisCoverage.COMPLETE:
            raise ValueError("only SUCCEEDED results may report COMPLETE coverage")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")

        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique within an AnalysisResult")
        available = set(evidence_ids)
        for candidate in self.candidates:
            if self.analysis_type is AnalysisType.PATENT and not isinstance(candidate, PatentCandidate):
                raise ValueError("PATENT results may contain only PatentCandidate values")
            if self.analysis_type is AnalysisType.LICENSE and not isinstance(candidate, LicenseCandidate):
                raise ValueError("LICENSE results may contain only LicenseCandidate values")
            missing = set(candidate.evidence_ids) - available
            if missing:
                raise ValueError(f"candidate references unknown evidence IDs: {sorted(missing)}")
        return self
