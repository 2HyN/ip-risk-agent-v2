"""근거 강도 점수 (설계 노트 §3 의 A 안).

우선도 판정은 바꾸지 않는다. 점수를 먼저 관측만 하면 되돌릴 것이 없고, 임계값을
고를 실제 데이터가 쌓인다 (§6-3).

세 항 모두 이미 근거 원장에 남아 있는 값이라 **점수를 근거로 되짚을 수 있다.**
이것이 임베딩 유사도(§3 의 B 안) 대비 가장 큰 실익이다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 가중치. 합이 1 이다. 라벨을 모으기 전이므로 사람이 정한 값이고, 그래서
#: 판정에 쓰지 않는다 (§5 — 라벨 없이 고른 임계값은 숫자만 있고 근거가 없다).
WEIGHT_ELEMENT_COVERAGE = 0.5
WEIGHT_CLAIM_BACKING = 0.3
WEIGHT_QUERY_REACH = 0.2

#: 점수 산식이 바뀌면 과거 기록의 뜻이 달라진다. 함께 남긴다 (§4.2).
SCORE_VERSION = "patent_evidence_strength_v1"


@dataclass(frozen=True, slots=True)
class EvidenceStrength:
    """0~1 의 근거 강도와 그것을 만든 항들."""

    score: float
    element_coverage: float
    claim_backing: float
    query_reach: float

    def as_metadata(self) -> dict[str, str]:
        """근거 원장·진단에 남길 형태. 값이 아니라 비율만 담는다."""
        return {
            "score_version": SCORE_VERSION,
            "evidence_strength": f"{self.score:.3f}",
            "element_coverage": f"{self.element_coverage:.3f}",
            "claim_backing": f"{self.claim_backing:.3f}",
            "query_reach": f"{self.query_reach:.3f}",
        }


def _ratio(numerator: int, denominator: int) -> float:
    """분모가 0 이면 0 이 아니라 **모른다**. 여기서는 0 으로 두되 호출자가
    분모 0 을 만들지 않도록 한다 (§4.1 — "모른다" 는 "낮다" 가 아니다)."""
    if denominator <= 0:
        return 0.0
    return min(1.0, numerator / denominator)


def evidence_strength(
    *,
    matched_elements: int,
    extracted_elements: int,
    claim_backed_evidence: int,
    patent_evidence: int,
    answered_queries: int,
    total_queries: int,
) -> EvidenceStrength:
    """근거 강도를 계산한다. 판정이 아니라 관측이다.

    * ``element_coverage`` — 문서에서 뽑은 구성 중 몇 개가 겹쳤는가
    * ``claim_backing`` — 인용된 특허 근거 중 청구항이 몇 할인가
    * ``query_reach`` — 만든 검색어 중 몇 개가 이 후보를 데려왔는가
    """
    element_coverage = _ratio(matched_elements, extracted_elements)
    claim_backing = _ratio(claim_backed_evidence, patent_evidence)
    query_reach = _ratio(answered_queries, total_queries)
    score = (
        WEIGHT_ELEMENT_COVERAGE * element_coverage
        + WEIGHT_CLAIM_BACKING * claim_backing
        + WEIGHT_QUERY_REACH * query_reach
    )
    return EvidenceStrength(
        score=round(score, 4),
        element_coverage=round(element_coverage, 4),
        claim_backing=round(claim_backing, 4),
        query_reach=round(query_reach, 4),
    )


__all__ = [
    "EvidenceStrength",
    "SCORE_VERSION",
    "WEIGHT_CLAIM_BACKING",
    "WEIGHT_ELEMENT_COVERAGE",
    "WEIGHT_QUERY_REACH",
    "evidence_strength",
]
