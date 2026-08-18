"""실제 provider 검증.

대역만으로는 "우리 코드가 우리 가정대로 동작한다"까지만 확인된다. 가정 자체가
틀렸는지는 진짜 응답을 받아 봐야 안다. KIPRIS 의 항목 태그가 item 이 아니라
searchResult 인 것, deps.dev 가 PyMuPDF 를 non-standard 로 답하는 것 모두
실제 호출로만 드러났다.

키가 없으면 건너뛴다. CI 에서 자격증명을 요구하지 않는다 (Master Spec 59-11).

    pytest tests/intelligence -m live
"""

from __future__ import annotations

import os

import pytest

from ip_risk_agent.intelligence.license.dependency_models import Ecosystem
from ip_risk_agent.intelligence.license.package_metadata import (
    HttpPackageMetadataProvider,
)
from ip_risk_agent.intelligence.license.policy import evaluate_expression
from ip_risk_agent.intelligence.patent.kipris import KiprisClient

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

KIPRIS_KEY = os.environ.get("KIPRIS_ACCESS_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL_ID", "")

needs_kipris = pytest.mark.skipif(not KIPRIS_KEY, reason="KIPRIS_ACCESS_KEY 없음")
needs_gemini = pytest.mark.skipif(
    not (GEMINI_KEY and GEMINI_MODEL), reason="GEMINI_API_KEY/GEMINI_MODEL_ID 없음"
)


# --------------------------------------------------------- 패키지 메타데이터


async def test_deps_dev_returns_a_standard_identifier():
    async with HttpPackageMetadataProvider() as provider:
        fact = await provider.get_license(Ecosystem.PYPI, "requests", "2.32.3")
    assert fact.license_expression == "Apache-2.0"
    assert fact.source == "deps.dev"


async def test_registry_fallback_recovers_a_license_deps_dev_cannot_map():
    # deps.dev 는 이 패키지를 non-standard 로 답한다. PyPI 원문에서 AGPL 을 되살린다.
    async with HttpPackageMetadataProvider() as provider:
        fact = await provider.get_license(Ecosystem.PYPI, "PyMuPDF", "1.24.0")
    assert fact.license_expression == "AGPL-3.0-only"
    assert fact.source == "pypi.org"
    assert fact.inferred_from_free_text is True
    # 최고 위험 등급이 확인 등급으로 내려가지 않는다.
    assert evaluate_expression(fact.license_expression).value == "POLICY_CONFLICT"


async def test_npm_metadata_lookup():
    async with HttpPackageMetadataProvider() as provider:
        fact = await provider.get_license(Ecosystem.NPM, "express", "4.19.2")
    assert fact.license_expression == "MIT"


async def test_missing_package_is_reported_as_not_found():
    from ip_risk_agent.intelligence.common.errors import ProviderFailureError

    async with HttpPackageMetadataProvider() as provider:
        with pytest.raises(ProviderFailureError) as caught:
            await provider.get_license(
                Ecosystem.PYPI, "ip-risk-agent-no-such-package-9x7", "1.0.0"
            )
    assert caught.value.category.value == "NOT_FOUND"
    assert caught.value.retryable is False


# --------------------------------------------------------------- KIPRIS


@needs_kipris
async def test_kipris_search_returns_normalized_application_numbers():
    async with KiprisClient(KIPRIS_KEY) as client:
        hits = await client.search("voice phishing detection", rows=5)
    assert hits, "검색어가 너무 좁으면 0건이 나온다"
    for hit in hits:
        assert hit.application_number.isdigit()


@needs_kipris
async def test_kipris_zero_result_is_not_an_error():
    # 실패와 0건을 구분한다. 이 검색어는 결과가 없어야 정상이다.
    async with KiprisClient(KIPRIS_KEY) as client:
        hits = await client.search("zzqq unlikely nonsense", rows=5)
    assert hits == []


@needs_kipris
async def test_kipris_detail_returns_an_abstract():
    async with KiprisClient(KIPRIS_KEY) as client:
        hits = await client.search("voice phishing detection", rows=3)
        document = await client.fetch_detail(hits[0].application_number)
    assert document.has_content
    assert document.abstract


@needs_kipris
async def test_kipris_rejects_a_bad_access_key():
    from ip_risk_agent.intelligence.common.errors import ProviderFailureError

    async with KiprisClient("definitely-not-a-valid-key") as client:
        try:
            hits = await client.search("voice phishing detection", rows=1)
        except ProviderFailureError as failure:
            assert failure.provider == "KIPRIS"
            return
    # 일부 공공 API 는 오류를 200 본문으로 돌려준다. 그때는 0건이어야 한다.
    assert hits == []


# --------------------------------------------------------------- Gemini


@needs_gemini
async def test_gemini_returns_output_matching_the_declared_schema():
    from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
    from ip_risk_agent.intelligence.gemini.schemas import TechnicalExtraction

    client = GoogleGenAIClient(GEMINI_MODEL, api_key=GEMINI_KEY)
    result = await client.generate(
        "다음 문서에서 기술 요소와 영문 2~3단어 검색어를 뽑아라.\n\n"
        "[seg-1]\n통화 음성에서 코덱 복호화 파라미터를 특징 벡터로 만들어 "
        "GMM 에 적용해 보이스피싱을 탐지한다.",
        TechnicalExtraction,
    )
    assert isinstance(result, TechnicalExtraction)
    assert result.is_technical is True
    assert result.search_queries


@needs_gemini
async def test_gemini_marks_a_non_technical_document():
    from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
    from ip_risk_agent.intelligence.gemini.schemas import TechnicalExtraction

    client = GoogleGenAIClient(GEMINI_MODEL, api_key=GEMINI_KEY)
    result = await client.generate(
        "다음 문서가 특허 검토 대상인지 판단하라.\n\n"
        "[seg-1]\n오늘 회의: 점심 메뉴는 김치찌개. 다음 회의는 화요일 3시.",
        TechnicalExtraction,
    )
    assert result.is_technical is False
