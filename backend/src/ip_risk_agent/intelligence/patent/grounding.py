"""모델 대조 결과의 검증과 우선순위 산정.

모델은 없는 근거를 그럴듯하게 지어낸다. 그래서 반환된 ID 가 실제 근거 집합에
있는지 코드가 확인한다. 하나라도 없으면 그 항목만 빼는 것이 아니라 **비교 전체를
폐기**한다 (Agent 3 Spec 19). 일부가 조작된 결과에서 나머지만 믿을 근거가 없다.

우선순위도 모델에게 맡기지 않는다. 검증된 근거의 개수와 종류로 코드가 계산한다
(Agent 3 Spec 20).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from iprisk_contracts.common import EvidenceType, ReviewPriority

from ..common.errors import MalformedProviderOutputError
from .quote import QuoteSpan, locate_quote
from ..gemini.schemas import PatentComparison, PatentComparisonV3


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
    #: 근거 ID -> 그 근거 본문 안에서 강조할 구간. 실재가 확인된 것만 담긴다.
    quote_spans: dict[str, QuoteSpan] = dataclass_field(default_factory=dict)
    #: 요소 단위 대조(v3)에서만 채워진다 — 겹친 **서로 다른 기술 요소**의 수.
    #: 같은 요소를 표현만 바꿔 반복해도 부풀지 않고, 상한이 추출 요소 수로
    #: 묶인다. v2 경로에서는 ``None`` 이라 기존 의미가 그대로다.
    distinct_match_count: int | None = None

    @property
    def match_count(self) -> int:
        if self.distinct_match_count is not None:
            return self.distinct_match_count
        return len(self.matched_elements)


def validate_comparison(
    comparison: PatentComparison,
    *,
    allowed_segment_ids: set[str],
    evidence_types: dict[str, EvidenceType],
    truncated_evidence_ids: frozenset[str] = frozenset(),
    evidence_bodies: dict[str, str] | None = None,
) -> GroundedComparison:
    """모델 출력을 검증한다. 통과하지 못하면 결과 전체를 버린다.

    ``evidence_types`` 는 등록된 특허 근거 ID 와 그 종류다. 청구항 근거가 있으면
    초록만 있을 때보다 판단의 무게가 다르므로 함께 본다.
    """
    matched: list[str] = []
    evidence_ids: list[str] = []
    has_claim = False
    bodies = evidence_bodies or {}
    spans: dict[str, QuoteSpan] = {}

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
        source_evidence_id = f"src:{element.source_segment_id}"
        for evidence_id, quote in (
            (source_evidence_id, element.source_quote),
            (element.patent_evidence_id, element.patent_quote),
        ):
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
            if not quote.strip():
                # 인용을 내지 않은 것은 허용한다. 하이라이트가 없을 뿐이다.
                continue
            body = bodies.get(evidence_id)
            if body is None:
                continue
            span = locate_quote(body, quote)
            if span is None:
                # 지어낸 인용이다. 일부가 조작된 결과에서 나머지만 믿을 근거가 없다.
                raise MalformedProviderOutputError(
                    "GEMINI",
                    f"comparison quoted text that is not in the evidence for "
                    f"{comparison.application_number}",
                )
            spans.setdefault(evidence_id, span)

    return GroundedComparison(
        application_number=comparison.application_number,
        matched_elements=matched,
        evidence_ids=evidence_ids,
        review_caveats=list(comparison.review_caveats),
        has_claim_evidence=has_claim,
        evidence_truncated=any(
            evidence_id in truncated_evidence_ids for evidence_id in evidence_ids
        ),
        quote_spans=spans,
    )


def validate_comparison_v3(
    comparison: PatentComparisonV3,
    *,
    element_count: int,
    allowed_segment_ids: set[str],
    evidence_types: dict[str, EvidenceType],
    truncated_evidence_ids: frozenset[str] = frozenset(),
    evidence_bodies: dict[str, str] | None = None,
) -> GroundedComparison:
    """요소 단위 대조(v3)의 검증. 원칙은 v2 와 같다 — 통과 못하면 전체 폐기.

    추가 검증은 ``element_index`` 의 범위 하나다. 목록에 없는 요소 번호를 만들면
    지어낸 근거와 같은 취급이다. ``match_count`` 는 겹친 **서로 다른 요소**의
    수로 계산한다 (계획 문서 §5 "match_count 재정의").
    """
    matched: list[str] = []
    evidence_ids: list[str] = []
    matched_indexes: set[int] = set()
    has_claim = False
    bodies = evidence_bodies or {}
    spans: dict[str, QuoteSpan] = {}

    for element in comparison.matched_elements:
        if not 0 <= element.element_index < element_count:
            raise MalformedProviderOutputError(
                "GEMINI",
                f"comparison referenced unknown technical element for "
                f"{comparison.application_number}",
            )
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

        matched_indexes.add(element.element_index)
        matched.append(element.explanation.strip())
        source_evidence_id = f"src:{element.source_segment_id}"
        for evidence_id, quote in (
            (source_evidence_id, element.source_quote),
            (element.patent_evidence_id, element.patent_quote),
        ):
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
            if not quote.strip():
                continue
            body = bodies.get(evidence_id)
            if body is None:
                continue
            span = locate_quote(body, quote)
            if span is None:
                raise MalformedProviderOutputError(
                    "GEMINI",
                    f"comparison quoted text that is not in the evidence for "
                    f"{comparison.application_number}",
                )
            spans.setdefault(evidence_id, span)

    return GroundedComparison(
        application_number=comparison.application_number,
        matched_elements=matched,
        evidence_ids=evidence_ids,
        review_caveats=list(comparison.review_caveats),
        has_claim_evidence=has_claim,
        evidence_truncated=any(
            evidence_id in truncated_evidence_ids for evidence_id in evidence_ids
        ),
        quote_spans=spans,
        distinct_match_count=len(matched_indexes),
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
