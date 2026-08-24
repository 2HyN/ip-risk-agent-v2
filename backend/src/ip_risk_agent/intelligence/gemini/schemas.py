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

    ID 로 가리키게 하고 코드가 대조한다. 인용도 같은 원칙으로 다룬다 — 모델이 낸
    구절이 본문에 **실제로 있는지 코드가 확인**하고, 없으면 그 대조 전체를 버린다.
    인용이 필요한 이유는 조각 안에서 다시 문장 단위로 좁혀야 하기 때문이다.
    """

    source_segment_id: str
    patent_evidence_id: str
    explanation: str
    source_quote: str = Field(
        default="",
        description="문서 조각에서 그대로 옮긴 구절. 한 글자도 바꾸지 않는다",
    )
    patent_quote: str = Field(
        default="",
        description="특허 근거에서 그대로 옮긴 구절. 한 글자도 바꾸지 않는다",
    )


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


class MatchedElementV3(_Output):
    """겹침 하나 — 요소 단위 대조(rag 전략)용.

    v2 와 다른 점은 ``element_index`` 하나다. 기술 요소가 ``[E0]..[En]`` 으로
    열거되어 오고, 모델은 **요소 번호 단위로** 겹침을 적는다. 여러 요소를 한
    항목에 묶는 것이 스키마 수준에서 불가능해진다 — MEDIUM 47건 중 38건이
    match_count==1 로 뭉친 원인(자유 대조의 서술 뭉침)에 대한 구조적 처방이다.
    """

    element_index: int = Field(description="기술 요소 목록의 [E숫자] 에서 그 숫자")
    source_segment_id: str
    patent_evidence_id: str
    explanation: str
    source_quote: str = Field(
        default="",
        description="문서 조각에서 그대로 옮긴 구절. 한 글자도 바꾸지 않는다",
    )
    patent_quote: str = Field(
        default="",
        description="특허 근거에서 그대로 옮긴 구절. 한 글자도 바꾸지 않는다",
    )


class PatentComparisonV3(_Output):
    """특허 한 건과의 대조 결과 — 요소 단위(rag 전략)."""

    application_number: str
    matched_elements: list[MatchedElementV3] = Field(default_factory=list)
    distinct_elements: list[str] = Field(
        default_factory=list, description="문서에만 있는 구성"
    )
    review_caveats: list[str] = Field(
        default_factory=list,
        description="검토자가 알아야 할 한계. 등급을 바꾸지 않는다",
    )


class RiskExplanationOutput(_Output):
    """이미 만들어진 Risk 에 붙일 설명과 권고.

    **판정을 바꾸지 못한다.** 등급도 Risk 의 존재도 규칙 엔진이 정한 그대로다.
    여기서는 이미 검증된 근거를 사람이 읽을 말로 옮기기만 한다.
    """

    summary: str = Field(description="왜 검토가 필요한지. 근거를 짚어 두세 문장")
    recommendation: str = Field(description="앞으로 무엇을 할지. 행동 수준의 권고")
    reference_evidence_ids: list[str] = Field(
        default_factory=list,
        description="설명이 근거로 삼은 evidence ID. 제시된 목록에 있는 것만",
    )


