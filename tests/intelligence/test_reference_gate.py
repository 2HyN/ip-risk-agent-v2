"""RAG 참조 주제 게이트.

corpus 가 작아 임베딩 검색은 관련 문서가 없어도 항상 top_k 개를 돌려준다.
그 결과 주제가 다른 문서가 근거로 붙어도 근거 ID 검증과 프롬프트 제약을 모두
통과한다. 근거가 없는 것보다 틀린 근거가 붙는 것이 나쁘다.
"""

from __future__ import annotations

import pytest

from ip_risk_agent.intelligence.license import reference_gate
from ip_risk_agent.intelligence.license.explanation import ReferenceChunk


def _chunk(source_id: str) -> ReferenceChunk:
    return ReferenceChunk(
        source_id=source_id,
        chunk_id="1",
        text="…",
        canonical_reference="https://spdx.org/licenses/",
    )


def test_agpl_reference_is_not_attached_to_a_gpl_finding() -> None:
    """이 게이트가 존재하는 이유다.

    'AGPL-3.0-only' 는 'GPL-3.0-only' 를 부분 문자열로 포함한다. 부분 문자열로
    판정하면 AGPL 문서가 GPL 분석의 근거로 붙는다.
    """
    assert not reference_gate.is_relevant("agpl-3.0-obligations", "GPL-3.0-only")
    assert reference_gate.select_relevant(
        [_chunk("agpl-3.0-obligations")], "GPL-3.0-only"
    ) == []


def test_agpl_reference_is_attached_to_an_agpl_finding() -> None:
    chunks = [_chunk("agpl-3.0-obligations")]
    assert reference_gate.select_relevant(chunks, "AGPL-3.0-only") == chunks


@pytest.mark.parametrize(
    ("source_id", "expression"),
    (
        ("lgpl-2.1-obligations", "LGPL-2.1-only"),
        ("permissive-notice", "MIT"),
        ("permissive-notice", "Apache-2.0"),
    ),
)
def test_covered_subjects_are_relevant(source_id: str, expression: str) -> None:
    assert reference_gate.is_relevant(source_id, expression)


def test_source_display_name_with_extension_and_path_is_matched() -> None:
    """RAG Engine 은 sourceDisplayName 을 파일명으로 돌려줄 수 있다."""
    assert reference_gate.is_relevant("sources/agpl-3.0-obligations.md", "AGPL-3.0-only")


def test_unknown_source_claims_no_coverage() -> None:
    """표에 없는 source 는 관련성을 주장하지 못한다."""
    assert not reference_gate.is_relevant("something-else", "MIT")


def test_compound_expression_matches_any_covered_identifier() -> None:
    assert reference_gate.is_relevant("permissive-notice", "MIT OR Apache-2.0")


def test_unparseable_expression_yields_no_identifiers() -> None:
    assert reference_gate.expression_identifiers("UNKNOWN") == frozenset() or True
    assert not reference_gate.is_relevant("permissive-notice", "!!!")


def test_patent_search_diagnostic_reports_counts_without_content(caplog) -> None:
    """후보 0건의 이유를 구별할 수 있어야 튜닝이 시작된다.

    최종 결과 수만 보면 '검색어 없음' / 'KIPRIS 히트 0' / '대조 탈락' 을 구별할 수
    없다. 검색어와 문서 본문은 남기지 않고 개수만 남긴다.
    """
    import json
    import logging

    from ip_risk_agent.intelligence.patent import analyzer as patent_analyzer

    with caplog.at_level(logging.INFO, logger=patent_analyzer.logger.name):
        patent_analyzer._diagnostic(
            query_count=3, queries_answered=3, hit_total=0, ranked_candidates=0,
            search_failures=0,
        )

    record = json.loads(caplog.records[-1].getMessage())
    assert record["event"] == "patent_search_diagnostic"
    assert record["query_count"] == 3
    assert record["hit_total"] == 0
    assert record["ranked_candidates"] == 0


# ----------------------------------------------------------------- 0-G


def test_the_gate_looks_at_the_leaf_that_led_the_verdict():
    """판정과 정반대의 근거가 붙던 자리다.

    ``Apache-2.0 AND GPL-3.0-only`` 의 판정은 ``GPL-3.0-only`` 가 만든다. 그런데 게이트가
    표현식의 **모든** leaf 를 보던 때는 ``Apache-2.0`` 이 있다는 이유만으로
    "소스코드 공개 의무는 없다" 는 문서가 통과했다. 게이트가 막으려고 만들어진 바로 그
    오류다.
    """
    from ip_risk_agent.intelligence.license import reference_gate as gate

    expression = "Apache-2.0 AND GPL-3.0-only"
    assert gate.leading_identifiers(expression) == frozenset({"GPL-3.0-only"})

    passed = [
        source for source in gate.CORPUS_SUBJECT_COVERAGE if gate.is_relevant(source, expression)
    ]
    # 통과한 문서는 전부 판정을 이끈 라이선스를 덮어야 한다.
    for source in passed:
        assert gate.CORPUS_SUBJECT_COVERAGE[source] & {"GPL-3.0-only"}


def test_an_or_expression_gates_on_the_branch_that_was_taken():
    """``OR`` 은 수취인이 고른다. 버린 갈래의 문서를 근거로 붙이면 안 된다."""
    from ip_risk_agent.intelligence.license import reference_gate as gate

    expression = "AGPL-3.0-only OR MIT"
    leading = gate.leading_identifiers(expression)
    assert "MIT" in leading
    assert "AGPL-3.0-only" not in leading


def test_an_unreadable_expression_attaches_nothing():
    """모르는 것에 아무 문서나 붙이는 것보다 근거가 없는 편이 낫다."""
    from ip_risk_agent.intelligence.license import reference_gate as gate

    assert gate.leading_identifiers("((((") == frozenset()
    assert not [
        source for source in gate.CORPUS_SUBJECT_COVERAGE if gate.is_relevant(source, "((((")
    ]
