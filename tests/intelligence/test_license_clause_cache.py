"""조항 검색 캐시 (§9.2 · 2-F).

같은 라이선스가 여러 패키지에 반복된다. 패키지마다 검색하면 같은 질의를 여러 번
보낸다. 이 캐시가 §7.6(주기적 재평가)의 선행이다 — 주기적으로 도는 조회는 의존성 수에
비례하므로, 캐시가 없으면 그 비용이 주기를 정하지 못하게 만든다.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from ip_risk_agent.core.workspaces.license_profile import (
    DistributionForm,
    LicenseDeploymentProfile,
    LinkingMode,
    ModificationState,
    WorkspaceLicensePolicy,
)
from ip_risk_agent.intelligence.license.cache import (
    InMemoryClauseSearchCache,
    clause_cache_key,
)
from ip_risk_agent.intelligence.license.explanation import reference_query
from ip_risk_agent.intelligence.license.policy import LicensePolicyOutcome

PROFILE = LicenseDeploymentProfile(
    distribution_form=DistributionForm.SAAS,
    modification=ModificationState.MODIFIED,
    linking=LinkingMode.STATIC,
    redistributes=True,
)


def _key(**overrides):
    base = {
        "license_expression": "AGPL-3.0-only",
        "outcome": LicensePolicyOutcome.POLICY_CONFLICT,
        "corpus_version": "2026-08-23.4",
        "axes_hash": PROFILE.axes_hash,
    }
    return clause_cache_key(**{**base, **overrides})


def test_the_deployment_axes_are_part_of_the_key():
    """빠지면 **SaaS workspace 의 조항 결과가 사내 전용 workspace 에 서빙된다.**

    D7 의 "워크스페이스는 서로 완전히 독립" 이 깨진다.
    """
    other = replace(PROFILE, distribution_form=DistributionForm.INTERNAL_ONLY)
    assert _key() != _key(axes_hash=other.axes_hash)


def test_the_corpus_version_is_part_of_the_key():
    """갱신 때 지우는 대신 키에 넣는다 (§9.2).

    지우는 절차가 없으니 **무효화 실패라는 실패 모드가 없고**, corpus 를 되돌리면 옛
    캐시가 살아 있어 롤백이 싸며, 두 판본을 나란히 두고 비교할 수 있다.
    """
    assert _key() != _key(corpus_version="2026-08-23.5")


def test_an_unknown_corpus_version_is_its_own_bucket():
    """모르는 검색을 아는 검색과 같은 칸에 넣으면 판본이 붙은 뒤에도 옛 답이 나온다."""
    assert _key() != _key(corpus_version=None)


def test_the_outcome_is_part_of_the_key():
    """판정이 질의에 들어간다. 다른 판정은 다른 조항을 찾는다."""
    assert _key() != _key(outcome=LicensePolicyOutcome.REVIEW_REQUIRED)


def test_the_pieces_cannot_run_into_each_other():
    """이어 붙이기만 하면 한 조각의 끝과 다음 조각의 시작이 섞여 다른 입력이 같은 키가 된다."""
    left = _key(license_expression="MIT", corpus_version="A")
    right = _key(license_expression="MIT|corpus=A", corpus_version="")
    assert left != right


def test_the_axes_actually_shape_the_query():
    """축이 질의에 안 들어가면 키에 넣을 이유도 없다.

    같은 LGPL 이라도 정적 링크를 묻는 것과 동적 링크를 묻는 것은 다른 조항을 찾는다.
    """
    static = reference_query(
        "LGPL-2.1-only", LicensePolicyOutcome.REVIEW_REQUIRED, PROFILE
    )
    dynamic = reference_query(
        "LGPL-2.1-only",
        LicensePolicyOutcome.REVIEW_REQUIRED,
        replace(PROFILE, linking=LinkingMode.DYNAMIC),
    )
    assert static != dynamic
    assert "정적 링크" in static and "동적 링크" in dynamic


def test_the_second_lookup_of_the_same_licence_does_not_search_again():
    from test_license import PROVIDER, FakeRetriever, make_artifact
    from ip_risk_agent.intelligence.license.analyzer import LicenseAnalyzer

    async def _policy(risk_workspace_id: str) -> WorkspaceLicensePolicy:
        return WorkspaceLicensePolicy(risk_workspace_id, "table-1", PROFILE)

    retriever = FakeRetriever()
    cache = InMemoryClauseSearchCache()
    analyzer = LicenseAnalyzer(
        PROVIDER,
        retriever=retriever,
        workspace_license_policy=_policy,
        clause_cache=cache,
    )

    async def scenario():
        first = await analyzer.analyze(make_artifact("PyMuPDF==1.24.0"))
        second = await analyzer.analyze(make_artifact("PyMuPDF==1.24.0"))
        return first, second

    first, second = asyncio.run(scenario())
    assert cache.hits == 1 and cache.misses == 1
    # 캐시가 답해도 근거는 그대로 붙는다. 아끼는 것은 호출이지 결과가 아니다.
    assert [e.evidence_id for e in first.evidence] == [
        e.evidence_id for e in second.evidence
    ]
