"""Patent Analyzer 회귀 테스트 (Agent 3 Spec 44).

KIPRIS 도 모델도 호출하지 않는다. 대역으로 검색 0건, 부분 실패, 환각 근거 같은
상황을 재현한다.
"""

from __future__ import annotations

import asyncio

import pytest
from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisStatus,
    AnalysisType,
    ArtifactKind,
    EvidenceType,
    ReviewPriority,
)

from ip_risk_agent.intelligence.common.errors import (
    FailureCategory,
    MalformedProviderOutputError,
    ProviderFailureError,
)
from ip_risk_agent.intelligence.common.evidence import EvidenceLedger
from ip_risk_agent.intelligence.gemini.client import PromptLibrary, ScriptedModelClient
from ip_risk_agent.intelligence.gemini.schemas import (
    MatchedElement,
    PatentComparison,
    TechnicalExtraction,
)
from ip_risk_agent.intelligence.patent import evidence_builder, grounding
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer
from ip_risk_agent.intelligence.patent.candidate_rank import rank_candidates
from ip_risk_agent.intelligence.patent.extraction import clamp_queries
from ip_risk_agent.intelligence.patent.kipris import (
    PatentDocument,
    PatentSearchHit,
    StaticPatentSearchProvider,
    normalize_application_number,
)

from test_license import make_artifact, run

DOC = (
    "통화 음성에서 코덱 복호화 과정의 파라미터를 특징 벡터로 구성하고, "
    "GMM 에 적용해 보이스피싱을 탐지한다."
)


def patent_artifact(text: str = DOC, **kwargs):
    kwargs.setdefault("logical_path", "docs/plan.md")
    kwargs.setdefault("kind", ArtifactKind.DOCUMENT_TEXT)
    kwargs.setdefault("analyzers", [AnalysisType.PATENT])
    return make_artifact(text, **kwargs)


PATENT_A = "1020080080388"
PATENT_B = "1020110101359"

HITS = {
    "voice phishing detection": [
        PatentSearchHit(PATENT_A, "보이스피싱 검출", "voice phishing detection"),
        PatentSearchHit(PATENT_B, "EER 기반 판정", "voice phishing detection"),
    ],
    "GMM feature vector": [
        PatentSearchHit(PATENT_A, "보이스피싱 검출", "GMM feature vector"),
    ],
}
DOCUMENTS = {
    PATENT_A: PatentDocument(
        PATENT_A,
        "보이스피싱 검출",
        abstract="SMV decoder parameters are used as a feature vector for GMM.",
    ),
    PATENT_B: PatentDocument(PATENT_B, "EER 기반 판정", abstract="EER and ROC based decision."),
}


def extraction(technical: bool = True, queries: list[str] | None = None):
    return TechnicalExtraction(
        is_technical=technical,
        technical_elements=["코덱 파라미터 특징 벡터", "GMM 적용"],
        search_queries=queries if queries is not None else list(HITS),
        source_segment_ids=["seg-1"],
    )


def comparison(
    application_number: str = PATENT_A,
    *,
    segment: str = "seg-1",
    evidence_id: str | None = None,
    count: int = 1,
):
    target = evidence_id or f"patent:{application_number}:abstract"
    return PatentComparison(
        application_number=application_number,
        matched_elements=[
            MatchedElement(
                source_segment_id=segment,
                patent_evidence_id=target,
                explanation=f"겹치는 구성 {index + 1}",
            )
            for index in range(count)
        ],
        distinct_elements=["통화 종료 연동"],
    )


# --------------------------------------------------------------- 단위


def test_application_number_normalization_merges_formats():
    assert normalize_application_number("10-2008-0080388") == PATENT_A
    assert normalize_application_number(PATENT_A) == PATENT_A


def test_repeated_hits_rank_first_and_order_is_deterministic():
    ranked = rank_candidates(HITS)
    assert [c.application_number for c in ranked] == [PATENT_A, PATENT_B]
    assert ranked[0].query_hits == 2
    assert rank_candidates(HITS) == ranked


def test_queries_are_clamped_to_three_words():
    # 다섯 단어를 넣으면 KIPRIS 가 0건을 돌려준다. 앞의 세 단어만 남긴다.
    assert clamp_queries(["voice phishing detection using GMM"]) == [
        "voice phishing detection"
    ]
    assert clamp_queries(["single"]) == []


def test_claim_evidence_is_registered_before_abstract():
    ledger = EvidenceLedger()
    document = PatentDocument(PATENT_A, "제목", abstract="초록", claims=["청구항 1"])
    evidence = evidence_builder.build_patent_evidence(document, ledger)
    assert evidence.evidence_ids[0].endswith(":claim:1")
    assert evidence.types[evidence.evidence_ids[0]] is EvidenceType.PATENT_CLAIM


def test_hallucinated_evidence_invalidates_the_whole_comparison():
    with pytest.raises(MalformedProviderOutputError):
        grounding.validate_comparison(
            comparison(evidence_id="patent:9999:claim:7"),
            allowed_segment_ids={"seg-1"},
            evidence_types={f"patent:{PATENT_A}:abstract": EvidenceType.PATENT_ABSTRACT},
        )


def test_unknown_source_segment_is_rejected():
    with pytest.raises(MalformedProviderOutputError):
        grounding.validate_comparison(
            comparison(segment="seg-does-not-exist"),
            allowed_segment_ids={"seg-1"},
            evidence_types={f"patent:{PATENT_A}:abstract": EvidenceType.PATENT_ABSTRACT},
        )


def test_priority_is_computed_from_verified_evidence_not_the_model():
    claim_backed = grounding.GroundedComparison(
        PATENT_A, ["a", "b"], ["x"], [], has_claim_evidence=True
    )
    abstract_only = grounding.GroundedComparison(
        PATENT_A, ["a"], ["x"], [], has_claim_evidence=False
    )
    uncertain = grounding.GroundedComparison(
        PATENT_A, ["a", "b"], ["x"], ["abstract only"], has_claim_evidence=True
    )
    assert grounding.suggested_priority(claim_backed) is ReviewPriority.HIGH
    assert grounding.suggested_priority(abstract_only) is ReviewPriority.LOW
    # 불확실 표시가 있으면 한 단계 낮춘다.
    assert grounding.suggested_priority(uncertain) is ReviewPriority.MEDIUM


def test_prompts_expose_a_stable_version():
    prompt = PromptLibrary().get("patent_compare_v1")
    assert prompt.prompt_version == "patent_compare_v1"
    assert "{segments}" in prompt.template


# --------------------------------------------------------------- Analyzer


def make_analyzer(responses, *, provider=None, cap=6):
    return PatentAnalyzer(
        provider or StaticPatentSearchProvider(HITS, DOCUMENTS),
        ScriptedModelClient(responses),
        candidate_cap=cap,
    )


def test_unapproved_artifact_is_rejected():
    from ip_risk_agent.intelligence.common.errors import ArtifactRejectedError

    analyzer = make_analyzer([extraction()])
    with pytest.raises(ArtifactRejectedError):
        run(analyzer.analyze(patent_artifact(approved=False)))


def test_non_technical_document_is_skipped_not_failed():
    analyzer = make_analyzer([extraction(technical=False)])
    result = run(analyzer.analyze(patent_artifact("오늘 회의 일정 정리")))
    assert result.status is AnalysisStatus.SKIPPED
    assert result.coverage is AnalysisCoverage.NONE


def test_technical_document_without_queries_is_inconclusive():
    analyzer = make_analyzer([extraction(queries=[])])
    result = run(analyzer.analyze(patent_artifact()))
    assert result.status is AnalysisStatus.INCONCLUSIVE


def test_zero_search_results_is_a_successful_complete_analysis():
    provider = StaticPatentSearchProvider({q: [] for q in HITS}, {})
    analyzer = make_analyzer([extraction()], provider=provider)
    result = run(analyzer.analyze(patent_artifact()))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.coverage is AnalysisCoverage.COMPLETE
    assert result.candidates == []


def test_total_search_failure_is_not_a_zero_result():
    provider = StaticPatentSearchProvider(failing_queries=set(HITS))
    analyzer = make_analyzer([extraction()], provider=provider)
    result = run(analyzer.analyze(patent_artifact()))
    assert result.status is AnalysisStatus.FAILED
    assert result.coverage is not AnalysisCoverage.COMPLETE
    assert result.provider_failures[0].provider == "KIPRIS"


def test_partial_query_failure_downgrades_coverage():
    provider = StaticPatentSearchProvider(
        HITS, DOCUMENTS, failing_queries={"GMM feature vector"}
    )
    analyzer = make_analyzer(
        [extraction(), comparison(PATENT_A), comparison(PATENT_B)], provider=provider
    )
    result = run(analyzer.analyze(patent_artifact()))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert any(f.provider == "KIPRIS" for f in result.provider_failures)


def test_matched_candidate_carries_verified_evidence():
    analyzer = make_analyzer([extraction(), comparison(PATENT_A), comparison(PATENT_B)])
    result = run(analyzer.analyze(patent_artifact()))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert {c.normalized_application_number for c in result.candidates} == {
        PATENT_A,
        PATENT_B,
    }
    known = {e.evidence_id for e in result.evidence}
    for candidate in result.candidates:
        assert set(candidate.evidence_ids) <= known
        assert candidate.matched_elements


def test_hallucinated_comparison_drops_the_candidate_and_lowers_coverage():
    analyzer = make_analyzer(
        [
            extraction(),
            comparison(PATENT_A, evidence_id="patent:0000:claim:9"),
            comparison(PATENT_B),
        ]
    )
    result = run(analyzer.analyze(patent_artifact()))
    numbers = {c.normalized_application_number for c in result.candidates}
    assert PATENT_A not in numbers
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert result.provider_failures[0].category == FailureCategory.MALFORMED_OUTPUT.value


def test_model_failure_during_comparison_is_recorded():
    analyzer = make_analyzer(
        [
            extraction(),
            ProviderFailureError("GEMINI", FailureCategory.TIMEOUT, "timed out"),
            comparison(PATENT_B),
        ]
    )
    result = run(analyzer.analyze(patent_artifact()))
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert any(f.provider == "GEMINI" for f in result.provider_failures)


def test_extraction_failure_fails_the_analysis():
    analyzer = make_analyzer(
        [ProviderFailureError("GEMINI", FailureCategory.UNAVAILABLE, "down")]
    )
    result = run(analyzer.analyze(patent_artifact()))
    assert result.status is AnalysisStatus.FAILED
    assert result.candidates == []


def test_candidate_schema_carries_no_legal_conclusion():
    analyzer = make_analyzer([extraction(), comparison(PATENT_A), comparison(PATENT_B)])
    result = run(analyzer.analyze(patent_artifact()))
    fields = set(result.candidates[0].model_dump())
    assert "infringement" not in " ".join(fields)
    assert result.candidates[0].suggested_review_priority in set(ReviewPriority)


def test_dependency_file_is_not_a_patent_target():
    analyzer = make_analyzer([extraction()])
    artifact = patent_artifact(logical_path="requirements.txt", kind=ArtifactKind.MANIFEST)
    assert analyzer.supports(artifact) is False


def test_analyzers_run_together_through_the_registry():
    from ip_risk_agent.intelligence.common.registry import AnalyzerRegistry
    from ip_risk_agent.intelligence.license.analyzer import LicenseAnalyzer
    from ip_risk_agent.intelligence.license.package_metadata import (
        StaticPackageMetadataProvider,
    )

    registry = AnalyzerRegistry(
        [
            make_analyzer([extraction(technical=False)]),
            LicenseAnalyzer(StaticPackageMetadataProvider({})),
        ]
    )
    artifact = patent_artifact(
        analyzers=[AnalysisType.PATENT, AnalysisType.LICENSE],
    )
    results = asyncio.run(registry.analyze(artifact))
    # 문서이므로 특허만 돌고 라이선스는 supports=False 다.
    assert [r.analysis_type for r in results] == [AnalysisType.PATENT]
