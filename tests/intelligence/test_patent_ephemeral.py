"""Ephemeral 청구항 인덱스 회귀 테스트.

핵심은 상위집합 불변식이다 — 독립항 전수와 베이스라인이 보던 앞 3개 청구항은
검색 결과와 무관하게 컨텍스트에 들어간다. 검색이 아무리 빗나가도 대조 입력이
현행보다 좁아지는 경로가 없어야 한다 (계획 문서 §6-4).
"""

from __future__ import annotations

from ip_risk_agent.intelligence.patent.claims import chunk_claims, parse_claims
from ip_risk_agent.intelligence.patent.ephemeral_index import (
    CandidateClaimIndex,
    select_context,
    tokenize,
)


def _chunks(claims: list[str], abstract: str = "요약이다."):
    return chunk_claims("1020200000001", parse_claims(claims), abstract)


def test_tokenize_bridges_spacing_differences_with_bigrams():
    # "온도센서" 와 "온도 센서" 가 bigram 을 공유한다.
    attached = set(tokenize("온도센서를 이용한 장치"))
    spaced = set(tokenize("온도 센서 장치"))
    assert attached & spaced & {"온도", "센서"} or ("온도" in attached and "온도" in spaced)


def test_retrieval_prefers_the_claim_that_shares_vocabulary():
    chunks = _chunks(
        [
            "신호를 수신하는 장치.",
            "제1항에 있어서, 켑스트럼 계수를 추출하는 장치.",
            "제1항에 있어서, 디스플레이를 회전시키는 장치.",
        ],
        abstract="",
    )
    dependents = [chunk for chunk in chunks if not chunk.independent]
    index = CandidateClaimIndex(dependents)
    retrieved = index.retrieve("켑스트럼 계수 추출", top_k=1)
    assert retrieved and retrieved[0].claim_number == 2


def test_retrieval_is_deterministic():
    chunks = _chunks(
        [
            "신호 장치.",
            "제1항에 있어서, 특징 벡터를 추출하는 장치.",
            "제1항에 있어서, 특징 벡터를 저장하는 장치.",
        ],
        abstract="",
    )
    dependents = [chunk for chunk in chunks if not chunk.independent]
    index = CandidateClaimIndex(dependents)
    first = [chunk.evidence_id for chunk in index.retrieve("특징 벡터", top_k=2)]
    second = [chunk.evidence_id for chunk in index.retrieve("특징 벡터", top_k=2)]
    assert first == second


def test_context_always_contains_independents_and_baseline_three():
    """검색과 무관한 상위집합 보장 — 요소가 어떤 종속항과도 안 겹쳐도 성립한다."""
    chunks = _chunks(
        [
            "음성 특징을 추출하는 장치.",  # 독립항 1
            "제1항에 있어서, 프레임을 나누는 장치.",  # 종속항 2 (baseline 창)
            "제1항에 있어서, 잡음을 제거하는 장치.",  # 종속항 3 (baseline 창)
            "제1항에 있어서, 임계값을 조정하는 장치.",  # 종속항 4
            "음성 특징 추출 방법.",  # 독립항 5 — 베이스라인은 못 보던 것
        ]
    )
    selection = select_context(chunks, ["전혀 무관한 요소"])
    ids = {chunk.evidence_id for chunk in selection.chunks}
    assert "patent:1020200000001:claim:1" in ids
    assert "patent:1020200000001:claim:2" in ids
    assert "patent:1020200000001:claim:3" in ids
    assert "patent:1020200000001:claim:5" in ids  # 4번째 이후 독립항 — 손실 ① 의 처방
    assert "patent:1020200000001:abstract" in ids
    assert not selection.incomplete


def test_relevant_dependent_claims_join_through_retrieval():
    chunks = _chunks(
        [
            "음성 신호 장치.",
            "제1항에 있어서, 화면을 밝게 하는 장치.",
            "제1항에 있어서, 배터리를 아끼는 장치.",
            "제1항에 있어서, 켑스트럼 계수를 추출하는 장치.",  # 4항 — baseline 밖
        ]
    )
    selection = select_context(chunks, ["켑스트럼 계수 추출"])
    ids = {chunk.evidence_id for chunk in selection.chunks}
    assert "patent:1020200000001:claim:4" in ids
    assert "patent:1020200000001:claim:4" in set(selection.retrieved_ids)


def test_budget_overflow_marks_context_incomplete():
    """필수 조각을 예산 때문에 떨어뜨리면 그 사실이 기록된다 — 강등의 입력이다."""
    many_independents = [f"독립 구성 {index} 를 갖는 장치. " + "설명 " * 80 for index in range(30)]
    chunks = _chunks(many_independents, abstract="")
    selection = select_context(chunks, ["아무 요소"], char_budget=1500)
    assert selection.incomplete
    assert selection.chunks  # 그래도 빈손은 아니다


def test_selection_is_deterministic():
    chunks = _chunks(
        [
            "신호 장치.",
            "제1항에 있어서, 특징 벡터를 추출하는 장치.",
            "제1항에 있어서, 특징 벡터를 비교하는 장치.",
            "제1항에 있어서, 결과를 표시하는 장치.",
        ]
    )
    elements = ["특징 벡터 추출", "결과 표시"]
    first = [chunk.evidence_id for chunk in select_context(chunks, elements).chunks]
    second = [chunk.evidence_id for chunk in select_context(chunks, elements).chunks]
    assert first == second
