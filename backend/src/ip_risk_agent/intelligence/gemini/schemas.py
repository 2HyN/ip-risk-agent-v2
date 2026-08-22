"""모델 출력 스키마.

모델은 자유 서술이 아니라 정해진 형태로만 답한다. 형태가 고정되어야 코드가 검증할 수
있고, 검증할 수 있어야 근거로 쓸 수 있다 (Agent 3 Spec 9).

법적 결론을 요구하는 필드는 두지 않는다. 침해 여부는 이 시스템의 판단 범위가 아니다
(Agent 3 Spec 11).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Output(BaseModel):
    """모델 출력 공통 규약. 모르는 필드는 거부한다."""

    model_config = ConfigDict(extra="forbid")


class TechnicalExtraction(_Output):
    """문서에서 기술 요소와 검색어를 뽑는다."""

    is_technical: bool = Field(
        description="특허 검토 대상이 되는 기술적 내용을 담고 있는가"
    )
    technical_elements: list[str] = Field(
        default_factory=list, description="구성 요소를 짧은 구절로"
    )
    search_queries: list[str] = Field(
        default_factory=list, description="영문 2~3단어 검색어"
    )
    source_segment_ids: list[str] = Field(
        default_factory=list, description="근거가 된 입력 segment"
    )


class MatchedElement(_Output):
    """겹치는 구성 하나. 양쪽 근거를 ID 로 가리킨다.

    인용문을 직접 만들게 하면 지어낸다. ID 로 가리키게 하고 코드가 대조한다.
    """

    source_segment_id: str
    patent_evidence_id: str
    explanation: str


class PatentComparison(_Output):
    """특허 한 건과의 대조 결과."""

    application_number: str
    matched_elements: list[MatchedElement] = Field(default_factory=list)
    distinct_elements: list[str] = Field(
        default_factory=list, description="문서에만 있는 구성"
    )
    review_caveats: list[str] = Field(
        default_factory=list,
        description="검토자가 알아야 할 한계. 등급을 바꾸지 않는다",
    )


class LicenseExplanationOutput(_Output):
    """정책 결과에 붙일 설명. 판정을 바꾸지 못한다."""

    summary: str
    obligations: list[str] = Field(default_factory=list)
    reference_chunk_ids: list[str] = Field(default_factory=list)
