"""rag 대조 전략의 end-to-end 회귀 테스트.

KIPRIS 도 모델도 부르지 않는다. 확장 검색 계획 + ephemeral 청구항 인덱스 +
요소 색인 대조(v3)의 전체 흐름을 대역으로 완주시키고, 검증 원칙(폐기·재질의)과
기록 문자열(전략 버전 연접)을 고정한다.
"""

from __future__ import annotations

from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisStatus,
    AnalysisType,
    ArtifactKind,
    ReviewPriority,
)

from ip_risk_agent.intelligence.gemini.client import ScriptedModelClient
from ip_risk_agent.intelligence.gemini.schemas import (
    MatchedElementV3,
    PatentComparisonV3,
    TechnicalExtraction,
)
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.kipris import (
    PatentDocument,
    PatentSearchHit,
    StaticPatentSearchProvider,
)
from ip_risk_agent.intelligence.patent.search_strategy import (
    EXPANDED_V1_PLAN,
)

from test_license import make_artifact, run

APP_NO = "1020200000001"

DOC = (
    "통화 음성에서 화자 분리를 수행하고, 프레임마다 켑스트럼 계수를 추출해 "
    "특징 벡터를 구성한 뒤 분류기에 적용한다."
)

CLAIMS = [
    "음성 신호에서 특징을 추출하는 장치.",
    "제1항에 있어서, 프레임마다 켑스트럼 계수를 추출하는 장치.",
    "제1항에 있어서, 화면 밝기를 조절하는 장치.",
    "제1항에 있어서, 통화 음성에서 화자 분리를 수행하는 장치.",
]

ABSTRACT = "통화 음성에서 화자를 분리하고 특징을 추출하는 발명이다."


def patent_artifact(text: str = DOC):
    return make_artifact(
        text,
        logical_path="/Google Drive user@example.com/docs/plan.md",
        kind=ArtifactKind.DOCUMENT_TEXT,
        analyzers=[AnalysisType.PATENT],
    )


def extraction():
    return TechnicalExtraction(
        is_technical=True,
        technical_elements=["켑스트럼 계수 추출", "화자 분리"],
        search_queries=["켑스트럼 계수", "화자 분리"],
        source_segment_ids=["seg-1"],
    )


def provider():
    hits = {
        "켑스트럼 계수": [
            PatentSearchHit(
                application_number=APP_NO, title="음성 분석 장치", query="켑스트럼 계수"
            )
        ],
        "화자 분리": [
            PatentSearchHit(
                application_number=APP_NO, title="음성 분석 장치", query="화자 분리"
            )
        ],
    }
    documents = {
        APP_NO: PatentDocument(
            application_number=APP_NO,
            title="음성 분석 장치",
            abstract=ABSTRACT,
            claims=CLAIMS,
        )
    }
    return StaticPatentSearchProvider(hits, documents)


def good_comparison():
    return PatentComparisonV3(
        application_number=APP_NO,
        matched_elements=[
            MatchedElementV3(
                element_index=0,
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{APP_NO}:claim:2",
                explanation="켑스트럼 계수 추출이 양쪽에 있다.",
                source_quote="켑스트럼 계수를 추출해",
                patent_quote="켑스트럼 계수를 추출하는 장치",
            ),
            MatchedElementV3(
                element_index=1,
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{APP_NO}:claim:4",
                explanation="화자 분리가 양쪽에 있다.",
                source_quote="화자 분리를 수행하고",
                patent_quote="화자 분리를 수행하는 장치",
            ),
        ],
        distinct_elements=["분류기 적용"],
        review_caveats=[],
    )


def rag_analyzer(model_client):
    return PatentAnalyzer(
        provider(),
        model_client,
        search_plan=EXPANDED_V1_PLAN,
        compare_strategy="rag",
    )


def test_rag_flow_completes_and_grades_by_distinct_elements():
    client = ScriptedModelClient([extraction(), good_comparison()])
    result = run(rag_analyzer(client).analyze(patent_artifact()))

    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.coverage is AnalysisCoverage.COMPLETE
    (candidate,) = result.candidates
    # 청구항 근거 + 서로 다른 요소 2개 겹침 → HIGH. 규칙표는 그대로다.
    assert candidate.suggested_review_priority is ReviewPriority.HIGH
    metadata = candidate.provider_metadata_safe
    assert metadata["compare_strategy"] == "rag"
    assert metadata["distinct_match_count"] == 2
    # 확장 계획이므로 RRF 순위 근거도 남는다.
    assert metadata["rank_version"] == "patent_rank_rrf_v2"

    # 4항(baseline 창 밖의 종속항)이 검색으로 컨텍스트에 들어와 근거가 됐다.
    assert f"patent:{APP_NO}:claim:4" in candidate.evidence_ids
    evidence_ids = {evidence.evidence_id for evidence in result.evidence}
    assert f"patent:{APP_NO}:claim:4" in evidence_ids


def test_rag_versions_record_the_full_machine():
    client = ScriptedModelClient([extraction(), good_comparison()])
    result = run(rag_analyzer(client).analyze(patent_artifact()))
    assert result.versions.prompt_version == (
        "patent_extract_v3+patent_compare_v3"
        "+search_expanded_v1+patent_rank_rrf_v2+claimchunk-v2+bm25-v1"
    )
    assert result.versions.analyzer_version == "patent-analyzer-1.1.0"


def test_rag_prompt_carries_indexed_elements_and_roles():
    client = ScriptedModelClient([extraction(), good_comparison()])
    run(rag_analyzer(client).analyze(patent_artifact()))
    compare_prompt = client.prompts[-1]
    assert "[E0] 켑스트럼 계수 추출" in compare_prompt
    assert "[E1] 화자 분리" in compare_prompt
    assert "독립항" in compare_prompt
    assert "종속항" in compare_prompt


def test_duplicate_element_indexes_do_not_inflate_match_count():
    duplicated = PatentComparisonV3(
        application_number=APP_NO,
        matched_elements=[
            MatchedElementV3(
                element_index=0,
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{APP_NO}:claim:2",
                explanation="켑스트럼 계수 추출이 겹친다.",
            ),
            MatchedElementV3(
                element_index=0,
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{APP_NO}:abstract",
                explanation="같은 요소를 표현만 바꿔 또 적었다.",
            ),
        ],
    )
    client = ScriptedModelClient([extraction(), duplicated])
    result = run(rag_analyzer(client).analyze(patent_artifact()))
    (candidate,) = result.candidates
    # distinct 요소는 1개 — 청구항 근거 + match 1 → MEDIUM. 반복 서술이 등급을
    # 밀어 올리지 못한다 (계획 문서 §5 "match_count 재정의").
    assert candidate.provider_metadata_safe["distinct_match_count"] == 1
    assert candidate.suggested_review_priority is ReviewPriority.MEDIUM


def test_unknown_element_index_discards_the_candidate_after_one_retry():
    bad = PatentComparisonV3(
        application_number=APP_NO,
        matched_elements=[
            MatchedElementV3(
                element_index=7,  # 목록에 없는 요소 번호 — 지어낸 근거와 같은 취급
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{APP_NO}:claim:2",
                explanation="없는 요소를 가리킨다.",
            )
        ],
    )
    client = ScriptedModelClient([extraction(), bad, bad])
    result = run(rag_analyzer(client).analyze(patent_artifact()))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.coverage is AnalysisCoverage.PARTIAL  # 후보가 미판정으로 남았다
    assert result.candidates == []
    assert len(client.prompts) == 3  # 추출 1 + 대조 1 + 재질의 1


def test_fabricated_quote_discards_the_candidate():
    forged = good_comparison().model_copy(deep=True)
    forged.matched_elements[0].patent_quote = "본문에 존재하지 않는 인용문이다"
    client = ScriptedModelClient([extraction(), forged, forged])
    result = run(rag_analyzer(client).analyze(patent_artifact()))
    assert result.candidates == []
    assert result.coverage is AnalysisCoverage.PARTIAL


def test_retry_recovers_when_the_second_answer_is_grounded():
    bad = PatentComparisonV3(
        application_number=APP_NO,
        matched_elements=[
            MatchedElementV3(
                element_index=7,
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{APP_NO}:claim:2",
                explanation="첫 응답은 어긋난다.",
            )
        ],
    )
    client = ScriptedModelClient([extraction(), bad, good_comparison()])
    result = run(rag_analyzer(client).analyze(patent_artifact()))
    assert result.coverage is AnalysisCoverage.COMPLETE
    (candidate,) = result.candidates
    assert candidate.suggested_review_priority is ReviewPriority.HIGH
