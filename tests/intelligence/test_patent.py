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
    abstract_only_single = grounding.GroundedComparison(
        PATENT_A, ["a"], ["x"], [], has_claim_evidence=False
    )
    abstract_only_multi = grounding.GroundedComparison(
        PATENT_A, ["a", "b"], ["x"], [], has_claim_evidence=False
    )
    uncertain = grounding.GroundedComparison(
        PATENT_A, ["a", "b"], ["x"], ["abstract only"], has_claim_evidence=True
    )
    assert grounding.suggested_priority(claim_backed) is ReviewPriority.HIGH
    assert grounding.suggested_priority(abstract_only_single) is ReviewPriority.LOW
    # KIPRIS 는 청구항을 주지 않는다. 초록만으로도 둘 이상 겹치면 올린다.
    assert grounding.suggested_priority(abstract_only_multi) is ReviewPriority.MEDIUM
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


def test_extraction_prompt_asks_for_korean_queries_against_kipris():
    """KIPRIS 는 한국 특허 DB 이고 색인 본문이 한국어다.

    v1 프롬프트는 영문 검색어를 지시했고, 배포 진단에서 query_count=3,
    search_failures=0, hit_total=0 으로 히트가 하나도 잡히지 않았다. 검색어 언어가
    색인 언어와 어긋나면 파이프라인의 나머지가 모두 정상이어도 결과가 0 건이다.
    """
    from ip_risk_agent.intelligence.gemini.client import PromptLibrary
    from ip_risk_agent.intelligence.patent.extraction import PROMPT_NAME

    prompt = PromptLibrary().get(PROMPT_NAME)
    assert prompt.prompt_version == "patent_extract_v2"
    assert "한국어 검색어" in prompt.template
    assert "영문 검색어는 결과가 0건" in prompt.template
    # 모든 단어를 포함해야 하므로 짧게 유지하라는 제약이 남아 있어야 한다.
    assert "2 단어를 기본으로 한다" in prompt.template


def test_previous_extraction_prompt_is_kept_for_provenance():
    """과거 결과에 기록된 prompt_version 을 되짚을 수 있어야 한다."""
    from ip_risk_agent.intelligence.gemini.client import PromptLibrary

    assert PromptLibrary().get("patent_extract_v1").prompt_version == "patent_extract_v1"


def test_kipris_error_body_is_a_provider_failure_not_an_empty_result():
    """KIPRIS 는 인증/등록 실패도 HTTP 200 으로 돌려주고 본문에만 사유를 남긴다.

    그것을 결과 0 건으로 넘기면 특허 분석이 coverage=COMPLETE 로 끝나며 없는
    권위를 주장한다. 운영에서 모든 질의가 hit_total=0, search_failures=0 이었고
    실은 한 번도 검색되지 않았다.
    """
    import asyncio

    import httpx

    from ip_risk_agent.intelligence.common.errors import (
        FailureCategory,
        ProviderFailureError,
    )
    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    body = (
        b"<response><header><resultCode>30</resultCode>"
        b"<resultMsg>AccessKey&amp;ServiceID Is Not Registerd Error</resultMsg>"
        b"</header><body><totalSearchCount></totalSearchCount></body></response>"
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    client = KiprisClient("unused-key", client=httpx.AsyncClient(transport=transport))

    async def scenario():
        with pytest.raises(ProviderFailureError) as failure:
            await client.search("음성")
        assert failure.value.category is FailureCategory.AUTH
        # 사유는 남기되 키는 절대 남기지 않는다.
        assert "resultCode=30" in failure.value.safe_message
        assert "unused-key" not in failure.value.safe_message
        await client.aclose()

    asyncio.run(scenario())


def test_kipris_success_without_hits_is_still_an_empty_result():
    """진짜 0 건 검색은 실패가 아니다. 둘을 섞으면 안 된다.

    실측한 성공 응답은 resultMsg 가 "NORMAL SERVICE." 로 채워져 온다. 메시지
    유무로 판정하면 정상 응답을 실패로 만든다 — 처음 구현이 실제로 그랬다.
    """
    import asyncio

    import httpx

    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    body = (
        b"<response><header><successYN>Y</successYN><resultCode>00</resultCode>"
        b"<resultMsg>NORMAL SERVICE.</resultMsg></header>"
        b"<body></body><count><totalCount>0</totalCount></count></response>"
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    client = KiprisClient("unused-key", client=httpx.AsyncClient(transport=transport))

    async def scenario():
        assert await client.search("음성") == []
        await client.aclose()

    asyncio.run(scenario())


def test_kipris_search_parses_the_documented_item_shape():
    """실측한 응답 형태를 고정한다.

    이전 구현은 `<searchResult>` 와 `applicationNo`/`inventionName` 을 기대했다.
    현재 서비스는 `<item>` 과 `applicationNumber`/`inventionTitle` 을 쓴다.
    """
    import asyncio

    import httpx

    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    body = (
        "<response><header><resultCode>00</resultCode>"
        "<resultMsg>NORMAL SERVICE.</resultMsg></header><body>"
        "<item><applicationNumber>1020170094969</applicationNumber>"
        "<inventionTitle>화자 인식 장치</inventionTitle>"
        "<applicationDate>20170727</applicationDate>"
        "<ipcNumber>G10L 17/04</ipcNumber></item>"
        "</body></response>"
    ).encode("utf-8")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    client = KiprisClient("unused-key", client=httpx.AsyncClient(transport=transport))

    async def scenario():
        hits = await client.search("화자 인식")
        assert len(hits) == 1
        assert hits[0].application_number == "1020170094969"
        assert hits[0].title == "화자 인식 장치"
        assert hits[0].metadata["ipc"] == "G10L 17/04"
        await client.aclose()

    asyncio.run(scenario())


def test_kipris_detail_includes_claims_not_only_the_abstract():
    """현재 경로는 청구항을 함께 제공한다.

    "KIPRIS 는 초록만 제공한다" 는 기존 제약은 이 경로에서는 사실이 아니다.
    청구항이 있으면 대조 근거의 질이 달라진다.
    """
    import asyncio

    import httpx

    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    body = (
        "<response><header><resultCode>00</resultCode>"
        "<resultMsg>NORMAL SERVICE.</resultMsg></header><body><item>"
        "<biblioSummaryInfoArray><biblioSummaryInfo>"
        "<inventionTitle>화자 인식</inventionTitle>"
        "</biblioSummaryInfo></biblioSummaryInfoArray>"
        "<abstractInfoArray><abstractInfo><astrtCont>요약</astrtCont>"
        "</abstractInfo></abstractInfoArray>"
        "<claimInfoArray><claimInfo><claim>청구항 1</claim></claimInfo>"
        "<claimInfo><claim>청구항 2</claim></claimInfo></claimInfoArray>"
        "</item></body></response>"
    ).encode("utf-8")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    client = KiprisClient("unused-key", client=httpx.AsyncClient(transport=transport))

    async def scenario():
        document = await client.fetch_detail("1020170094969")
        assert document.title == "화자 인식"
        assert document.abstract == "요약"
        assert document.claims == ["청구항 1", "청구항 2"]
        assert document.has_content
        assert document.metadata["claim_count"] == "2"
        await client.aclose()

    asyncio.run(scenario())
