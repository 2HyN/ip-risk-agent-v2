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
    # Security Gate 가 실제로 넘기는 형태다. canonical logical path 는 앞에 `/` 가
    # 붙는다 (`_canonical_logical_path`). 예전 fixture 는 이 `/` 가 없어서
    # 근거 참조가 보존 정책에 걸리는 결함을 통과시켰다.
    kwargs.setdefault("logical_path", "/Google Drive user@example.com/docs/plan.md")
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
    truncated = grounding.GroundedComparison(
        PATENT_A,
        ["a", "b"],
        ["x"],
        ["청구항이 구현 세부를 한정하지 않음"],
        has_claim_evidence=True,
        evidence_truncated=True,
    )
    caveat_only = grounding.GroundedComparison(
        PATENT_A,
        ["a", "b"],
        ["x"],
        ["같은 용어가 다른 뜻으로 쓰임"],
        has_claim_evidence=True,
    )
    assert grounding.suggested_priority(claim_backed) is ReviewPriority.HIGH
    assert grounding.suggested_priority(abstract_only_single) is ReviewPriority.LOW
    # KIPRIS 는 청구항을 주지 않는다. 초록만으로도 둘 이상 겹치면 올린다.
    assert grounding.suggested_priority(abstract_only_multi) is ReviewPriority.MEDIUM
    # 잘린 근거로 내린 판단은 원문 일부만 본 것이므로 한 단계 낮춘다.
    assert grounding.suggested_priority(truncated) is ReviewPriority.MEDIUM
    # 모델이 남긴 참고사항은 등급을 바꾸지 않는다. 실측에서 대조 80 건 중 77 건이
    # 표시를 달아 HIGH 가 한 번도 나오지 않았다.
    assert grounding.suggested_priority(caveat_only) is ReviewPriority.HIGH


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


def test_every_evidence_reference_survives_the_retention_policy():
    """분석기가 만든 근거 참조는 canonical 수용을 통과해야 한다.

    이 둘은 서로 다른 plane 에 있고 각각은 옳았다. Security Gate 는 logical path 를
    `/` 로 시작하는 canonical 형태로 만들고, 보존 정책은 `/` 로 시작하는 참조를
    로컬 절대경로 유출로 보고 거부한다. 이음매를 아무도 시험하지 않아서 특허 Risk 가
    한 건도 만들어지지 않았다. 그 이음매를 여기서 고정한다.
    """
    from ip_risk_agent.application.risk_reconcile.retention import (
        EvidenceRetentionPolicy,
        sanitize_reference,
    )

    analyzer = make_analyzer([extraction(), comparison(PATENT_A), comparison(PATENT_B)])
    result = run(analyzer.analyze(patent_artifact()))
    assert result.candidates, "이음매를 확인하려면 후보가 있어야 한다"

    policy = EvidenceRetentionPolicy()
    referenced = {
        evidence_id
        for candidate in result.candidates
        for evidence_id in candidate.evidence_ids
    }
    assert referenced, "후보가 근거를 참조해야 한다"
    checked = 0
    for evidence in result.evidence:
        if evidence.evidence_id not in referenced:
            continue
        sanitize_reference(evidence.reference, policy)
        checked += 1
    assert checked == len(referenced)


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


def test_a_transient_timeout_is_retried_once_and_recovers():
    """검색 다섯 건이 한꺼번에 타임아웃해 분석 전체가 실패한 적이 있다.

    개별 요청의 결함이 아니라 그 시점 provider 가 느렸던 것이므로, GET 한 번은
    다시 걸어본다.
    """
    import httpx

    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    body = (
        b"<response><header><resultCode>00</resultCode>"
        b"<resultMsg>NORMAL SERVICE.</resultMsg></header><body><items>"
        b"<item><applicationNumber>1020080080388</applicationNumber>"
        b"<inventionTitle>test</inventionTitle></item>"
        b"</items></body></response>"
    )
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=body)

    client = KiprisClient(
        "unused-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_backoff_seconds=0.0,
    )

    async def scenario():
        hits = await client.search("음성")
        assert [hit.application_number for hit in hits] == ["1020080080388"]
        assert len(calls) == 2
        await client.aclose()

    asyncio.run(scenario())


def test_an_auth_failure_is_not_retried():
    """다시 걸어도 같은 답이 오고, 호출량만 쓴다."""
    import httpx

    from ip_risk_agent.intelligence.common.errors import (
        FailureCategory,
        ProviderFailureError,
    )
    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, content=b"<response/>")

    client = KiprisClient(
        "unused-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_backoff_seconds=0.0,
    )

    async def scenario():
        with pytest.raises(ProviderFailureError) as failure:
            await client.search("음성")
        assert failure.value.category is FailureCategory.AUTH
        assert len(calls) == 1
        await client.aclose()

    asyncio.run(scenario())


def test_the_priority_diagnostic_separates_the_three_paths_to_medium(caplog):
    """MEDIUM 은 세 갈래로 만들어진다. 결과만 보면 가릴 수 없다.

    실측에서 특허 Risk 33 건이 전부 MEDIUM 이었는데, 겹치는 구성이 하나뿐인지
    청구항 근거가 없는지 HIGH 에서 강등된 것인지 알 길이 없었다. 이 진단이 그것을
    가른다.
    """
    import json
    import logging

    analyzer = make_analyzer([extraction(), comparison(PATENT_A), comparison(PATENT_B)])
    with caplog.at_level(logging.INFO, logger="ip_risk_agent.intelligence.patent.analyzer"):
        run(analyzer.analyze(patent_artifact()))

    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
    ]
    priority = [r for r in records if r.get("event") == "patent_priority_diagnostic"]
    assert priority, "후보마다 등급 진단이 나와야 한다"
    for record in priority:
        assert set(record) == {
            "schema_version",
            "event",
            "match_count",
            "has_claim_evidence",
            "caveat_count",
            "evidence_truncated",
            "evidence_strength",
            "segment_count",
            "distinct_segments",
            "priority",
        }
        # 판정을 되짚을 수 있어야 한다.
        assert isinstance(record["match_count"], int)
        assert isinstance(record["has_claim_evidence"], bool)
        assert record["priority"] in {"LOW", "MEDIUM", "HIGH"}
    # 본문이나 표시 문구는 남기지 않는다.
    dumped = json.dumps(priority, ensure_ascii=True)
    assert "겹치는" not in dumped
    assert DOC[:12] not in dumped


def test_a_document_is_split_into_reviewable_segments():
    """원문은 저장하지 않으므로 검토 화면이 보여줄 문맥은 조각 그 자체다.

    통짜 하나였을 때는 대조가 (문서 전체 × 청구항) 쌍만 만들 수 있었고, Risk 에
    남는 원문 근거는 매칭된 부분이 아니라 파일 앞부분이었다.
    """
    from ip_risk_agent.connectors.common.segmentation import (
        MAX_SEGMENT_CHARS,
        split_document,
    )

    body = "\n\n".join(
        [
            "# 제목",
            "첫 문단이다. " * 20,
            "```\n코드 한 줄\n또 한 줄\n```",
            "마지막 문단이다. " * 20,
        ]
    )
    segments = split_document(body)
    assert len(segments) > 1, "통짜 하나로 두면 가리킬 곳이 없다"
    assert all(len(s.text) <= MAX_SEGMENT_CHARS for s in segments)
    assert all(s.line_start is not None and s.line_end is not None for s in segments)
    assert all(s.segment_id.startswith(f"L{s.line_start}-{s.line_end}") for s in segments)
    # ID 가 겹치면 근거 원장이 같은 ID 에 다른 내용을 받아 거부한다.
    assert len({s.segment_id for s in segments}) == len(segments)
    # 줄 범위가 겹치지 않고 앞으로만 간다.
    starts = [s.line_start for s in segments]
    assert starts == sorted(starts)
    # 코드 울타리는 안에서 잘리지 않는다.
    fenced = [s for s in segments if "코드 한 줄" in s.text]
    assert fenced and "또 한 줄" in fenced[0].text


def test_an_empty_document_yields_no_segments():
    from ip_risk_agent.connectors.common.segmentation import split_document

    assert split_document("") == []
    assert split_document("\n\n   \n") == []


def test_a_block_without_sentence_breaks_is_still_bounded_and_uniquely_identified():
    """문장 경계가 없는 덩어리도 상한 안으로 들어와야 한다.

    상한을 넘긴 채로 두면 근거 원장이 뒤를 잘라내고, 잘린 뒤쪽은 검토 화면에 영영
    나타나지 않는다. 하이라이트가 그 부분을 짚어야 할 때 보여 줄 것이 없다.
    그리고 한 블록이 여러 조각으로 갈리면 줄 범위가 같아지므로 ID 가 겹친다.
    """
    from ip_risk_agent.connectors.common.segmentation import (
        MAX_SEGMENT_CHARS,
        split_document,
    )
    from ip_risk_agent.intelligence.common.evidence import EvidenceLedger

    body = "x" * (MAX_SEGMENT_CHARS * 3 + 40)
    segments = split_document(body)
    assert len(segments) >= 3
    assert all(len(s.text) <= MAX_SEGMENT_CHARS for s in segments)
    assert len({s.segment_id for s in segments}) == len(segments)
    # 잘려서 사라진 글자가 없어야 한다.
    assert "".join(s.text for s in segments) == body

    # 원장이 받아들여야 한다. 예전에는 같은 ID 에 다른 내용이 와서 거부됐다.
    ledger = EvidenceLedger()
    from iprisk_contracts.common import EvidenceType

    for segment in segments:
        ledger.add(
            f"src:{segment.segment_id}",
            EvidenceType.SOURCE_EXCERPT,
            segment.text,
            "sample.md",
            {},
        )
    assert len(ledger) == len(segments)
    assert ledger.truncated_ids == frozenset()


def test_a_quota_error_is_rate_limited_and_not_retried():
    """호출 한도 초과를 재시도하면 한도를 한 번 더 쓸 뿐이다.

    실측 응답은 resultCode=22 / LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR 다.
    이것이 UNAVAILABLE 로 분류되면 재시도 대상에 들어가 상황을 악화시킨다.
    """
    import httpx

    from ip_risk_agent.intelligence.common.errors import (
        FailureCategory,
        ProviderFailureError,
    )
    from ip_risk_agent.intelligence.patent.kipris import KiprisClient

    body = (
        b"<response><header><resultCode>22</resultCode>"
        b"<resultMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</resultMsg>"
        b"</header><body><items/></body></response>"
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    client = KiprisClient(
        "unused-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_backoff_seconds=0.0,
    )

    async def scenario():
        with pytest.raises(ProviderFailureError) as failure:
            await client.search("음성")
        assert failure.value.category is FailureCategory.RATE_LIMITED
        assert len(calls) == 1, "한도 초과는 다시 걸지 않는다"
        await client.aclose()

    asyncio.run(scenario())


def test_the_cache_spends_a_kipris_call_only_once_per_thing():
    """무료 한도는 월 1,000 회다. 같은 것을 다시 받으면 재검증이 불가능해진다.

    분석 한 건이 11 회쯤 쓰므로 문서 20 건 재분석이 220 회다. 실제로 하루 만에
    한도를 소진했고, 그 호출의 대부분은 같은 특허를 다시 받아온 것이었다.
    """
    from datetime import datetime, timedelta, timezone

    from ip_risk_agent.intelligence.patent.cache import (
        CachingPatentSearchProvider,
        InMemoryPatentResponseCache,
    )

    class CountingProvider:
        def __init__(self) -> None:
            self.searches = 0
            self.details = 0

        async def search(self, query, *, rows=5):
            self.searches += 1
            return list(HITS.get(query, []))[:rows]

        async def fetch_detail(self, application_number):
            self.details += 1
            return DOCUMENTS[application_number]

    inner = CountingProvider()
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    clock = {"value": now}
    provider = CachingPatentSearchProvider(
        inner, InMemoryPatentResponseCache(), clock=lambda: clock["value"]
    )

    async def scenario():
        query = "voice phishing detection"
        first = await provider.search(query)
        second = await provider.search(query)
        assert first == second
        assert inner.searches == 1, "같은 검색어를 두 번 받지 않는다"

        a = await provider.fetch_detail(PATENT_A)
        b = await provider.fetch_detail(PATENT_A)
        assert a == b
        assert inner.details == 1, "같은 출원번호를 두 번 받지 않는다"

        # 검색은 오래 두지 않는다. 새 공보가 나오면 달라진다.
        clock["value"] = now + timedelta(days=8)
        await provider.search(query)
        assert inner.searches == 2
        # 등록된 특허의 서지는 그 사이에 바뀌지 않는다.
        await provider.fetch_detail(PATENT_A)
        assert inner.details == 1

    asyncio.run(scenario())


def test_a_broken_cache_does_not_break_the_analysis():
    """캐시는 있으면 좋은 것이지 정확성의 일부가 아니다.

    캐시 때문에 분석이 실패하면 아끼려던 호출을 오히려 더 쓰게 된다.
    """
    from ip_risk_agent.intelligence.patent.cache import CachingPatentSearchProvider

    class BrokenCache:
        async def get_search(self, key):
            raise RuntimeError("cache is down")

        async def put_search(self, key, value):
            raise RuntimeError("cache is down")

        async def get_document(self, application_number):
            raise RuntimeError("cache is down")

        async def put_document(self, application_number, value):
            raise RuntimeError("cache is down")

    provider = CachingPatentSearchProvider(
        StaticPatentSearchProvider(HITS, DOCUMENTS), BrokenCache()
    )

    async def scenario():
        hits = await provider.search("voice phishing detection")
        assert hits, "캐시가 죽어도 검색은 되어야 한다"
        document = await provider.fetch_detail(PATENT_A)
        assert document.application_number == PATENT_A

    asyncio.run(scenario())


def test_the_cache_wrapper_still_closes_the_provider():
    """감쌌다고 자원 수명 관리가 사라지지 않는다.

    production 의 close_callbacks 가 이 이름을 부른다.
    """
    from ip_risk_agent.intelligence.patent.cache import (
        CachingPatentSearchProvider,
        InMemoryPatentResponseCache,
    )

    class ClosableProvider(StaticPatentSearchProvider):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    inner = ClosableProvider(HITS, DOCUMENTS)
    provider = CachingPatentSearchProvider(inner, InMemoryPatentResponseCache())
    asyncio.run(provider.aclose())
    assert inner.closed


CORPUS_PATH = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "fixtures"
    / "kipris"
    / "corpus.json"
)


def test_the_offline_corpus_goes_through_the_real_parsing_path():
    """대역으로 갈아끼우면 파싱이 검증되지 않는다.

    이 프로젝트에서 가장 오래 걸린 결함 둘이 파싱과 응답 해석에 있었다 — 오류
    본문을 "결과 0 건" 으로 넘긴 것과 서비스 경로가 달라 인증되지 않은 것.
    코퍼스는 실제 응답과 같은 XML 로 만들어 KiprisClient 에 물린다.
    """
    from ip_risk_agent.intelligence.patent.offline_corpus import (
        load_corpus,
        offline_kipris_client,
    )

    corpus = load_corpus(CORPUS_PATH, acknowledge_synthetic=True)
    client = offline_kipris_client(corpus, acknowledge_synthetic=True)

    async def scenario():
        hits = await client.search("보이스피싱 탐지", rows=5)
        assert hits, "코퍼스가 적중을 내야 한다"
        assert all(h.application_number.isdigit() for h in hits)
        assert all(h.title for h in hits)

        # 넣은 단어를 모두 포함해야 적중이다. 검색어가 길수록 줄어든다.
        narrow = await client.search("보이스피싱 탐지 열폭주", rows=5)
        assert narrow == []

        document = await client.fetch_detail(hits[0].application_number)
        assert document.title
        assert document.claims, "청구항이 파싱되어야 한다"
        assert document.abstract
        assert document.has_content
        # 실측과 같이 청구항은 근거 상한에 걸리지 않는다.
        assert all(len(claim) <= 600 for claim in document.claims)

        missing = await client.fetch_detail("9999999999999")
        assert not missing.has_content
        await client.aclose()

    asyncio.run(scenario())


def test_the_offline_corpus_is_never_wired_into_production():
    """합성 특허 본문이 실제 판단에 쓰이면 안 된다."""
    from pathlib import Path

    import ip_risk_agent.composition.production as production

    source = Path(production.__file__).read_text(encoding="utf-8")
    assert "offline_corpus" not in source


def test_the_evidence_strength_score_is_recorded_but_does_not_judge():
    """점수를 먼저 관측만 하면 되돌릴 것이 없다 (설계 노트 §6-3).

    라벨을 모으기 전의 가중치는 사람이 정한 값이라 판정에 쓸 근거가 없다.
    """
    from ip_risk_agent.intelligence.patent.score import (
        SCORE_VERSION,
        evidence_strength,
    )

    weak = evidence_strength(
        matched_elements=1, extracted_elements=8,
        claim_backed_evidence=0, patent_evidence=1,
        answered_queries=1, total_queries=5,
    )
    strong = evidence_strength(
        matched_elements=6, extracted_elements=6,
        claim_backed_evidence=3, patent_evidence=3,
        answered_queries=5, total_queries=5,
    )
    assert 0.0 <= weak.score < strong.score <= 1.0
    assert strong.score == 1.0
    assert weak.as_metadata()["score_version"] == SCORE_VERSION

    # 분모가 0 이어도 터지지 않는다. 다만 그것은 "모른다" 이지 "낮다" 가 아니므로
    # 호출자가 분모 0 을 만들지 않아야 한다 (§4.1).
    unknown = evidence_strength(
        matched_elements=0, extracted_elements=0,
        claim_backed_evidence=0, patent_evidence=0,
        answered_queries=0, total_queries=0,
    )
    assert unknown.score == 0.0


def test_the_score_reaches_the_candidate_metadata_without_changing_the_grade():
    analyzer = make_analyzer([extraction(), comparison(PATENT_A), comparison(PATENT_B)])
    result = run(analyzer.analyze(patent_artifact()))
    assert result.candidates
    for candidate in result.candidates:
        meta = candidate.provider_metadata_safe
        assert "evidence_strength" in meta
        assert "score_version" in meta
        assert 0.0 <= float(meta["evidence_strength"]) <= 1.0
        # 등급은 여전히 규칙이 정한다.
        assert candidate.suggested_review_priority in set(ReviewPriority)


def test_a_fabricated_quote_discards_the_whole_comparison():
    """인용도 ID 와 같은 원칙으로 다룬다.

    일부가 조작된 결과에서 나머지만 믿을 근거가 없다 (Agent 3 Spec 19).
    """
    from ip_risk_agent.intelligence.gemini.schemas import MatchedElement, PatentComparison

    bodies = {
        "src:seg-1": "코덱 복호화 파라미터를 특징 벡터로 구성한다.",
        f"patent:{PATENT_A}:abstract": "SMV decoder parameters are used as a feature vector.",
    }
    fabricated = PatentComparison(
        application_number=PATENT_A,
        matched_elements=[
            MatchedElement(
                source_segment_id="seg-1",
                patent_evidence_id=f"patent:{PATENT_A}:abstract",
                explanation="겹친다",
                source_quote="문서에 없는 문장을 지어냈다",
                patent_quote="",
            )
        ],
    )
    with pytest.raises(MalformedProviderOutputError):
        grounding.validate_comparison(
            fabricated,
            allowed_segment_ids={"seg-1"},
            evidence_types={f"patent:{PATENT_A}:abstract": EvidenceType.PATENT_ABSTRACT},
            evidence_bodies=bodies,
        )


def test_a_real_quote_yields_a_span_into_the_stored_evidence():
    """조각까지 좁힌 다음, 그 안에서 다시 문장으로 좁힌다."""
    from ip_risk_agent.intelligence.gemini.schemas import MatchedElement, PatentComparison

    body = "앞 문장이다.\n코덱 복호화  파라미터를 특징 벡터로 구성한다.\n뒤 문장이다."
    bodies = {"src:seg-1": body, f"patent:{PATENT_A}:abstract": "초록 본문이 여기에 있다."}
    grounded = grounding.validate_comparison(
        PatentComparison(
            application_number=PATENT_A,
            matched_elements=[
                MatchedElement(
                    source_segment_id="seg-1",
                    patent_evidence_id=f"patent:{PATENT_A}:abstract",
                    explanation="겹친다",
                    # 모델은 공백을 다듬어 인용한다. 그래도 찾아야 한다.
                    source_quote="코덱 복호화 파라미터를 특징 벡터로 구성한다",
                    patent_quote="초록 본문이 여기에 있다",
                )
            ],
        ),
        allowed_segment_ids={"seg-1"},
        evidence_types={f"patent:{PATENT_A}:abstract": EvidenceType.PATENT_ABSTRACT},
        evidence_bodies=bodies,
    )
    span = grounded.quote_spans["src:seg-1"]
    # 위치는 저장된 원문 기준이어야 화면이 그대로 강조할 수 있다.
    assert body[span.start : span.end] == "코덱 복호화  파라미터를 특징 벡터로 구성한다"
    assert f"patent:{PATENT_A}:abstract" in grounded.quote_spans


def test_a_missing_quote_is_allowed_and_simply_has_no_highlight():
    from ip_risk_agent.intelligence.gemini.schemas import MatchedElement, PatentComparison

    grounded = grounding.validate_comparison(
        PatentComparison(
            application_number=PATENT_A,
            matched_elements=[
                MatchedElement(
                    source_segment_id="seg-1",
                    patent_evidence_id=f"patent:{PATENT_A}:abstract",
                    explanation="겹친다",
                )
            ],
        ),
        allowed_segment_ids={"seg-1"},
        evidence_types={f"patent:{PATENT_A}:abstract": EvidenceType.PATENT_ABSTRACT},
        evidence_bodies={"src:seg-1": "아무 문장", f"patent:{PATENT_A}:abstract": "초록"},
    )
    assert grounded.quote_spans == {}
    assert grounded.match_count == 1


def test_the_synthetic_corpus_refuses_casual_use(monkeypatch):
    """빠뜨린 인자 하나로 합성 근거가 흘러들면 안 된다.

    여기서 나온 특허 본문은 실제 공보가 아니다. 그것이 사용자 화면에 Risk 로 뜨면
    거짓 근거다. 그래서 기본값을 "거부" 로 둔다.
    """
    from ip_risk_agent.intelligence.patent.offline_corpus import (
        SYNTHETIC_OPT_IN_ENV,
        SyntheticCorpusRefused,
        load_corpus,
        offline_kipris_client,
    )

    monkeypatch.delenv(SYNTHETIC_OPT_IN_ENV, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    with pytest.raises(SyntheticCorpusRefused):
        load_corpus(CORPUS_PATH)
    with pytest.raises(SyntheticCorpusRefused):
        offline_kipris_client({})

    # 개발 환경에서 의도를 켜면 열린다.
    monkeypatch.setenv(SYNTHETIC_OPT_IN_ENV, "1")
    assert load_corpus(CORPUS_PATH)

    # 프로덕션에서는 의도를 켜도 열리지 않는다.
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SyntheticCorpusRefused):
        load_corpus(CORPUS_PATH, acknowledge_synthetic=True)
    with pytest.raises(SyntheticCorpusRefused):
        offline_kipris_client({}, acknowledge_synthetic=True)
