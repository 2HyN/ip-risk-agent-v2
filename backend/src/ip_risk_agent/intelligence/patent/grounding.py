"""모델 대조 결과의 검증과 우선순위 산정.

모델은 없는 근거를 그럴듯하게 지어낸다. 그래서 반환된 ID 가 실제 근거 집합에
있는지 코드가 확인한다. 하나라도 없으면 그 항목만 빼는 것이 아니라 **비교 전체를
폐기**한다 (Agent 3 Spec 19). 일부가 조작된 결과에서 나머지만 믿을 근거가 없다.

우선순위도 모델에게 맡기지 않는다. 검증된 근거의 개수와 종류로 코드가 계산한다
(Agent 3 Spec 20).
"""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts.common import EvidenceType, ReviewPriority

from ..common.errors import MalformedProviderOutputError
from ..gemini.schemas import PatentComparison


@dataclass(frozen=True)
class GroundedComparison:
    """검증을 통과한 대조 결과."""

    application_number: str
    matched_elements: list[str]
    evidence_ids: list[str]
    uncertainty_flags: list[str]
    has_claim_evidence: bool

    @property
    def match_count(self) -> int:
        return len(self.matched_elements)


def validate_comparison(
    comparison: PatentComparison,
    *,
    allowed_segment_ids: set[str],
    evidence_types: dict[str, EvidenceType],
) -> GroundedComparison:
    """모델 출력을 검증한다. 통과하지 못하면 결과 전체를 버린다.

    ``evidence_types`` 는 등록된 특허 근거 ID 와 그 종류다. 청구항 근거가 있으면
    초록만 있을 때보다 판단의 무게가 다르므로 함께 본다.
    """
    matched: list[str] = []
    evidence_ids: list[str] = []
    has_claim = False

    for element in comparison.matched_elements:
        if element.source_segment_id not in allowed_segment_ids:
            raise MalformedProviderOutputError(
                "GEMINI",
                f"comparison referenced unknown source segment for "
                f"{comparison.application_number}",
            )
        evidence_type = evidence_types.get(element.patent_evidence_id)
        if evidence_type is None:
            raise MalformedProviderOutputError(
                "GEMINI",
                f"comparison referenced unknown patent evidence for "
                f"{comparison.application_number}",
            )
        if evidence_type is EvidenceType.PATENT_CLAIM:
            has_claim = True

        matched.append(element.explanation.strip())
        for evidence_id in (
            f"src:{element.source_segment_id}",
            element.patent_evidence_id,
        ):
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)

    return GroundedComparison(
        application_number=comparison.application_number,
        matched_elements=matched,
        evidence_ids=evidence_ids,
        uncertainty_flags=list(comparison.uncertainty_flags),
        has_claim_evidence=has_claim,
    )


def suggested_priority(comparison: GroundedComparison) -> ReviewPriority:
    """검토 우선순위. 침해 가능성이 아니라 '먼저 볼 것'의 순서다.

    청구항 근거가 있으면 권리 범위와 직접 대조된 것이므로 무겁게 본다.
    불확실 표시가 붙으면 한 단계 낮춘다. 확신이 낮은 것을 위로 올리면
    사람이 가짜 우선순위를 따라가게 된다.
    """
    if comparison.match_count == 0:
        return ReviewPriority.LOW

    if comparison.has_claim_evidence and comparison.match_count >= 2:
        level = ReviewPriority.HIGH
    elif comparison.has_claim_evidence or comparison.match_count >= 3:
        level = ReviewPriority.MEDIUM
    else:
        level = ReviewPriority.LOW

    if comparison.uncertainty_flags and level is ReviewPriority.HIGH:
        return ReviewPriority.MEDIUM
    return level
