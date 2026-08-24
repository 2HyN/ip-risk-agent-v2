"""청구항 파서·청킹 회귀 테스트 (`docs/PATENT_RAG_ENHANCEMENT_PLAN.md` §6-5).

파서 불변식 둘을 고정한다 — 텍스트를 버리지도 고치지도 않는다, 번호는
전부-파싱-또는-전부-위치다. 두 번째가 깨지면 근거 원장 ID 충돌로 분석 전체가
죽는 경로가 있다.
"""

from __future__ import annotations

from ip_risk_agent.intelligence.patent.claims import (
    CHUNK_LIMIT,
    CHUNK_OVERLAP,
    chunk_claims,
    parse_claims,
)


def test_independent_and_dependent_claims_are_told_apart():
    claims = parse_claims(
        [
            "음성 신호에서 특징 벡터를 추출하는 장치.",
            "제1항에 있어서, 상기 특징 벡터는 켑스트럼 계수를 포함하는 장치.",
            "청구항 1에 있어서, 상기 추출은 프레임 단위로 수행되는 장치.",
        ]
    )
    assert [claim.independent for claim in claims] == [True, False, False]
    assert claims[1].depends_on == (1,)
    assert claims[2].depends_on == (1,)


def test_multi_reference_dependency_expands_ranges():
    claims = parse_claims(
        [
            "특징 추출 장치.",
            "분류 장치.",
            "판정 장치.",
            "제1항 내지 제3항 중 어느 한 항에 있어서, 임계값을 조정하는 장치.",
        ]
    )
    assert claims[3].depends_on == (1, 2, 3)


def test_reference_without_isseoseo_stays_independent():
    # "제1항의 장치를 이용하는 방법" 은 실질 독립항이다. 오판의 방향을
    # "종속항을 독립항으로"(전수 포함 쪽)로 통일한다 — fail-open.
    claims = parse_claims(
        [
            "음성 특징 추출 장치.",
            "제1항의 장치를 이용하여 보이스피싱을 탐지하는 방법.",
        ]
    )
    assert claims[1].independent


def test_numbered_headers_are_used_when_all_parse():
    claims = parse_claims(
        [
            "청구항 1 음성 특징을 추출하는 장치.",
            "청구항 3 제1항에 있어서, 프레임 단위로 추출하는 장치.",
        ]
    )
    assert [claim.number for claim in claims] == [1, 3]


def test_partial_or_duplicate_numbering_falls_back_to_positions():
    """혼합 금지 — 일부만 번호가 읽히면 전부 위치 번호로 강등한다.

    섞으면 파싱된 번호와 위치 번호가 충돌해 근거 원장이 같은 ID 로 다른 내용을
    받고, 그 ValueError 가 분석 전체를 죽인다.
    """
    partially_numbered = parse_claims(
        [
            "제 2 항 어딘가에서 온 청구항.",
            "번호 머리가 없는 청구항.",
        ]
    )
    assert [claim.number for claim in partially_numbered] == [1, 2]

    duplicated = parse_claims(
        [
            "청구항 1 첫 번째.",
            "청구항 1 같은 번호가 또 온다.",
        ]
    )
    assert [claim.number for claim in duplicated] == [1, 2]


def test_kipris_numbered_heads_are_parsed():
    """KIPRIS 상세조회 실측 형식 — "1. 본문…". 삭제로 번호에 구멍이 나도
    표기 번호를 쓰므로 ID 가 어긋나지 않는다."""
    claims = parse_claims(
        [
            "1. 외부 장치와 통신을 수행하는 통신모듈을 포함하는 장치.",
            "3. 제 1 항에 있어서, 상기 통신모듈은 무선인 장치.",
        ]
    )
    assert [claim.number for claim in claims] == [1, 3]
    assert claims[1].depends_on == (1,)


def test_deleted_claims_are_not_chunked():
    chunks = chunk_claims(
        "1020200000001",
        parse_claims(["1. 특징을 추출하는 장치.", "2. 삭제", "3. 제 1 항에 있어서, 좁힌다."]),
        abstract="",
    )
    numbers = {chunk.claim_number for chunk in chunks}
    assert numbers == {1, 3}


def test_parser_never_alters_text():
    raw = ["청구항 1 상기 장치는 신호를 변환한다.", "제1항에 있어서, 더 좁힌다."]
    claims = parse_claims(raw)
    assert [claim.text for claim in claims] == raw


def test_short_claim_is_a_single_chunk_with_canonical_id():
    chunks = chunk_claims(
        "1020200000001",
        parse_claims(["음성 특징을 추출하는 장치."]),
        abstract="",
    )
    assert [chunk.evidence_id for chunk in chunks] == [
        "patent:1020200000001:claim:1"
    ]
    assert chunks[0].part is None


def test_long_claim_splits_with_overlap_and_loses_nothing():
    long_text = "가나다라마바사아자차카타파하; " * 60  # 900자 이상
    chunks = chunk_claims("1020200000001", parse_claims([long_text]), abstract="")
    assert len(chunks) >= 2
    assert all(len(chunk.text) <= CHUNK_LIMIT for chunk in chunks)
    assert [chunk.part for chunk in chunks] == list(range(1, len(chunks) + 1))
    # 겹침 덕에 이웃 조각이 경계를 공유한다.
    assert chunks[1].text[:CHUNK_OVERLAP] in chunks[0].text
    # 전량 보존 — 원문 비공백 문자가 조각 어딘가에 전부 있다.
    joined = "".join(chunk.text for chunk in chunks)
    assert set(long_text.replace(" ", "")) <= set(joined)


def test_abstract_is_chunked_too():
    chunks = chunk_claims(
        "1020200000001",
        parse_claims(["짧은 청구항."]),
        abstract="이 발명은 통화 음성에서 특징을 추출한다.",
    )
    assert chunks[-1].evidence_id == "patent:1020200000001:abstract"
    assert chunks[-1].claim_number is None
