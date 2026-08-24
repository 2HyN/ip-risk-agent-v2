"""한국 청구항 파싱과 청킹.

현행 대조는 청구항 **앞의 3개**만 본다 (`evidence_builder.py` max_claims=3).
한국 특허는 물건항+방법항 두 계열의 독립항이 흔하고, 심사관이 짚는 종속항
한정("제1항에 있어서 …")은 4항 이후에 많다 — 위치 기반 절단이 그것을 통째로
버린다. 이 모듈이 청구항 전체를 대조 가능한 조각으로 만든다.

## 파서 불변식 — 텍스트를 버리지도 고치지도 않는다

번호·의존 관계 파싱은 **ID 와 분류에만** 쓰인다. 조각 본문은 원문 그대로다.
파싱이 실패해도 조각은 남는다 — 실패가 베이스라인보다 나빠지는 경로를 차단한다.

## 번호는 전부-파싱-또는-전부-위치

일부 청구항만 번호가 읽히면 파싱된 번호와 위치 번호가 충돌해 근거 원장이
같은 ID 로 다른 내용을 받게 된다 (원장은 그것을 오류로 던져 **분석 전체가
죽는다**). 그래서 문서 단위로 가른다 — 모든 청구항의 번호가 읽히고 유일할
때만 그 번호를 쓰고, 아니면 전부 위치 번호(1부터)로 강등한다 (계획 문서 §6-5).

## 의존 판정은 fail-open

"제N항에 있어서" / "청구항 N에 있어서" / "…중 어느 한 항에 있어서" 가 머리
구간에 있어야 종속항이다. "제1항의 장치를 이용하는 방법" 처럼 참조만 하는
실질 독립항은 독립항으로 남긴다 — 오판의 방향을 "종속항을 독립항으로"
(전수 포함 쪽) 로 통일한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 청커가 바뀌면 과거 판정의 뜻이 달라진다. ``prompt_version`` 에 연접된다.
CLAIMS_VERSION = "claimchunk-v1"

#: 근거 원장의 발췌 상한과 정렬한다 (`common/evidence.py` MAX_EXCERPT_CHARS).
#: 조각이 상한 이하면 원장 절단이 일어나지 않아 evidence_truncated 강등의
#: 오발동(주로 긴 초록)이 사라진다.
CHUNK_LIMIT = 600
CHUNK_TARGET = 500
#: 인용문이 조각 경계에 걸려도 한쪽 조각에서 찾을 수 있게 겹친다.
CHUNK_OVERLAP = 80

#: 청구항 머리 번호. "청구항 1" / "【청구항 1】" / "제 1 항" / "1. " 표기를 읽는다.
#: 마지막 형식은 KIPRIS 상세조회 실측(2026-08-24) — claimInfo 본문이
#: "1. 외부 장치와 …" 처럼 번호+마침표로 시작한다. 삭제된 청구항이 목록에서
#: 빠져도 표기 번호를 쓰면 ID 가 어긋나지 않는다.
_HEAD = re.compile(
    r"^\s*(?:【\s*)?(?:청구항\s*(\d+)|제\s*(\d+)\s*항|(\d+)\s*[.．])(?:\s*】)?"
)

#: "N. 삭제" — 보정으로 삭제된 청구항. 기술 내용이 없으므로 조각으로 만들지
#: 않는다 (KIPRIS 실측 형식).
_DELETED_CLAIM = re.compile(r"^\s*(?:\d+\s*[.．])?\s*삭제\s*\.?\s*$")

#: 의존 판정 창. 머리 구간에서만 본다 — 본문 중간의 인용은 의존이 아니다.
_DEPENDENCY_WINDOW = 120

#: "…에 있어서" 로 끝나는 인용 구간이 있어야 종속항이다.
_DEPENDENCY = re.compile(
    r"(?:제\s*\d+\s*항|청구항\s*\d+)"  # 첫 인용
    r"(?:\s*(?:내지|또는|및|,)\s*(?:제\s*\d+\s*항|청구항\s*\d+))*"  # 이어지는 인용
    r"(?:\s*중\s*어느\s*한\s*항)?"
    r"\s*에\s*있어서"
)

_CLAIM_NUMBER = re.compile(r"(?:제\s*(\d+)\s*항|청구항\s*(\d+))")
_RANGE = re.compile(
    r"(?:제\s*(\d+)\s*항|청구항\s*(\d+))\s*내지\s*(?:제\s*(\d+)\s*항|청구항\s*(\d+))"
)

#: 600자 초과 청구항을 나눌 구성요소 경계. 앞에서부터 순서대로 찾는다.
_SPLIT_BOUNDARIES = (";", "며,", "고,", "와,", "과,", "하는 단계", "부,")


@dataclass(frozen=True)
class ParsedClaim:
    """청구항 하나. ``number`` 는 표기 번호 또는 위치 번호다."""

    number: int
    text: str
    depends_on: tuple[int, ...]

    @property
    def independent(self) -> bool:
        return not self.depends_on


@dataclass(frozen=True)
class ClaimChunk:
    """대조 컨텍스트의 최소 단위. 원장 ID 체계를 그대로 쓴다."""

    evidence_id: str
    application_number: str
    #: ``None`` 이면 초록 조각이다.
    claim_number: int | None
    #: 분할되지 않았으면 ``None``.
    part: int | None
    independent: bool
    text: str


def _head_number(raw: str) -> int | None:
    match = _HEAD.match(raw)
    if match is None:
        return None
    return int(match.group(1) or match.group(2) or match.group(3))


def _dependencies(raw: str) -> tuple[int, ...]:
    window = raw[:_DEPENDENCY_WINDOW]
    match = _DEPENDENCY.search(window)
    if match is None:
        return ()
    cited = match.group(0)
    numbers: set[int] = set()
    for low_a, low_b, high_a, high_b in _RANGE.findall(cited):
        low = int(low_a or low_b)
        high = int(high_a or high_b)
        if low <= high and high - low <= 200:
            numbers.update(range(low, high + 1))
    for single_a, single_b in _CLAIM_NUMBER.findall(cited):
        numbers.add(int(single_a or single_b))
    return tuple(sorted(numbers))


def parse_claims(raw_claims: list[str]) -> list[ParsedClaim]:
    """청구항 목록을 파싱한다. 본문은 한 글자도 고치지 않는다."""
    cleaned = [claim for claim in raw_claims if claim.strip()]
    if not cleaned:
        return []

    parsed_numbers = [_head_number(claim) for claim in cleaned]
    numbers_usable = (
        all(number is not None for number in parsed_numbers)
        and len(set(parsed_numbers)) == len(parsed_numbers)
    )

    claims: list[ParsedClaim] = []
    for position, raw in enumerate(cleaned, start=1):
        number = parsed_numbers[position - 1] if numbers_usable else position
        claims.append(
            ParsedClaim(
                number=number,  # type: ignore[arg-type]
                text=raw,
                depends_on=_dependencies(raw),
            )
        )
    return claims


def _split_long(text: str) -> list[str]:
    """상한을 넘는 본문을 구성요소 경계에서 나눈다. 겹침을 두고, 버리지 않는다."""
    if len(text) <= CHUNK_LIMIT:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        remaining = text[start:]
        if len(remaining) <= CHUNK_LIMIT:
            pieces.append(remaining)
            break
        window = remaining[:CHUNK_LIMIT]
        cut = -1
        for boundary in _SPLIT_BOUNDARIES:
            found = window.rfind(boundary, CHUNK_TARGET - 160, CHUNK_LIMIT)
            if found >= 0:
                cut = max(cut, found + len(boundary))
        if cut < CHUNK_OVERLAP + 1:
            cut = CHUNK_LIMIT
        pieces.append(remaining[:cut])
        # 겹침만큼 되돌아가되 반드시 전진한다 — 무한 루프 방지.
        start += max(cut - CHUNK_OVERLAP, 1)
    return pieces


def _chunk_ids(base: str, pieces: list[str]) -> list[tuple[str, int | None]]:
    if len(pieces) == 1:
        return [(base, None)]
    return [(f"{base}:part:{index}", index) for index in range(1, len(pieces) + 1)]


def chunk_claims(
    application_number: str,
    claims: list[ParsedClaim],
    abstract: str,
) -> list[ClaimChunk]:
    """청구항 전량과 초록을 조각으로 만든다.

    조각 순서는 (청구항 목록 순서, part 순서) 로 결정론적이다.
    """
    chunks: list[ClaimChunk] = []
    for claim in claims:
        if _DELETED_CLAIM.match(claim.text):
            # 보정 삭제 청구항 — 기술 내용이 없어 대조 대상이 아니다.
            continue
        pieces = _split_long(claim.text)
        base = f"patent:{application_number}:claim:{claim.number}"
        for (evidence_id, part), piece in zip(_chunk_ids(base, pieces), pieces):
            chunks.append(
                ClaimChunk(
                    evidence_id=evidence_id,
                    application_number=application_number,
                    claim_number=claim.number,
                    part=part,
                    independent=claim.independent,
                    text=piece,
                )
            )

    stripped = abstract.strip()
    if stripped:
        pieces = _split_long(stripped)
        base = f"patent:{application_number}:abstract"
        for (evidence_id, part), piece in zip(_chunk_ids(base, pieces), pieces):
            chunks.append(
                ClaimChunk(
                    evidence_id=evidence_id,
                    application_number=application_number,
                    claim_number=None,
                    part=part,
                    independent=False,
                    text=piece,
                )
            )
    return chunks


__all__ = [
    "CHUNK_LIMIT",
    "CHUNK_OVERLAP",
    "CHUNK_TARGET",
    "CLAIMS_VERSION",
    "ClaimChunk",
    "ParsedClaim",
    "chunk_claims",
    "parse_claims",
]
