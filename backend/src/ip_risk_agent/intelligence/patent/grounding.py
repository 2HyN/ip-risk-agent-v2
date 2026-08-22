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
    #: 모델이 남긴 검토 참고사항. **등급을 바꾸지 않는다.**
    review_caveats: list[str]
    has_claim_evidence: bool
    #: 대조가 본 근거가 원문의 일부였는지. 모델에게 묻지 않고 원장이 기록한 사실이다.
    evidence_truncated: bool = False

    @property
    def match_count(self) -> int:
        return len(self.matched_elements)


def validate_comparison(
    comparison: PatentComparison,
    *,
    allowed_segment_ids: set[str],
    evidence_types: dict[str, EvidenceType],
    truncated_evidence_ids: frozenset[str] = frozenset(),
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
        review_caveats=list(comparison.review_caveats),
        has_claim_evidence=has_claim,
        evidence_truncated=any(
            evidence_id in truncated_evidence_ids for evidence_id in evidence_ids
        ),
    )


def suggested_priority(comparison: GroundedComparison) -> ReviewPriority:
    """검토 우선순위. 침해 가능성이 아니라 '먼저 볼 것'의 순서다.

    청구항 근거가 있으면 권리 범위와 직접 대조된 것이므로 무겁게 본다. 초록 근거만
    있어도 겹치는 구성이 둘 이상이면 MEDIUM 으로 올린다.

    ## 강등은 코드가 아는 사실로만 한다

    예전에는 모델이 남긴 ``uncertainty_flags`` 가 비어 있지 않으면 HIGH 를 한 단계
    내렸다. 실측에서 대조 80 건 중 77 건이 표시를 달았고, **HIGH 자격을 갖춘 13 건이
    13 건 모두 강등**되어 HIGH 가 한 번도 나오지 않았다. 표시의 내용을 보면 이유가
    분명하다 — "선행 특허 청구항에 구체적인 알고리즘이 제시되어 있지 않음" 처럼
    대부분 **특허의 서술 범위에 대한 논평**이지 우리 판단의 불확실성이 아니었다.
    "판단이 어려웠던 이유를 적으라" 고 물으면 모델은 언제나 무언가를 적는다.

    그래서 강등 조건을 코드가 검증할 수 있는 사실로 좁혔다. 지금은 하나다 —
    **대조가 본 근거가 잘렸는가.** 잘린 근거로 내린 판단은 원문 일부만 본 것이다.
    실측에서 청구항은 중앙값 176 자로 거의 잘리지 않으므로, 이 조건이 걸리는 것은
    드물고 그래서 걸릴 때 뜻이 있다.

    모델의 관찰은 ``review_caveats`` 로 남아 검토자에게 보이지만 등급을 바꾸지 않는다.
    판정은 규칙 엔진이 하고 모델은 설명한다.
    """
    if comparison.match_count == 0:
        return ReviewPriority.LOW

    if comparison.has_claim_evidence and comparison.match_count >= 2:
        level = ReviewPriority.HIGH
    elif comparison.has_claim_evidence or comparison.match_count >= 2:
        level = ReviewPriority.MEDIUM
    else:
        level = ReviewPriority.LOW

    if comparison.evidence_truncated and level is ReviewPriority.HIGH:
        return ReviewPriority.MEDIUM
    return level
