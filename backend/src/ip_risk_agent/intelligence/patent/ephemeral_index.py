"""분석 단위 일시(ephemeral) 청구항 인덱스.

후보 특허의 청구항 조각을 분석 1회 수명의 in-memory BM25 인덱스에 넣고, 문서의
기술 요소를 질의로 관련 조각만 고른다. 외부 호출이 없고(임베딩 미사용), 분석이
끝나면 인덱스도 함께 사라진다 — 어떤 특허가 후보로 떴는지 자체가 비공개 문서의
파생 정보라 영속화하지 않는다 (계획 문서 §2 "영속 특허 RAG corpus 불채택").

## 검색은 컨텍스트를 늘리는 방향으로만 작동한다

컨텍스트 = **독립항 전수 ∪ 베이스라인이 보던 앞 3개 청구항 ∪ 검색된 종속항**.
독립항과 앞 3개는 검색과 무관하게 항상 들어간다 — 검색이 못 데려와도 정보량이
베이스라인의 진부분집합이 되는 경로를 구조적으로 막는다 (계획 문서 §6-4).

## 결정론

토큰화·BM25·동점 정렬이 전부 순수 함수다. 같은 조각·같은 질의면 같은 선택이다.
비결정 요소는 이 모듈 밖의 모델 호출 하나뿐이다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .claims import ClaimChunk

#: 검색기가 바뀌면 과거 판정의 뜻이 달라진다. ``prompt_version`` 에 연접된다.
INDEX_VERSION = "bm25-v1"

_WORD = re.compile(r"[가-힣A-Za-z0-9]+")
_HANGUL = re.compile(r"[가-힣]{2,}")

_K1 = 1.2
_B = 0.75


def tokenize(text: str) -> list[str]:
    """어절 + 한글 문자 bigram.

    조사 부착("온도센서를" vs "온도 센서")과 띄어쓰기 차이를 bigram 이 흡수한다.
    """
    words = _WORD.findall(text.lower())
    tokens = list(words)
    for word in words:
        for run in _HANGUL.findall(word):
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _chunk_sort_key(chunk: ClaimChunk) -> tuple[int, int, str]:
    # 초록은 청구항 뒤로. part 없음(None)은 0.
    number = chunk.claim_number if chunk.claim_number is not None else 10**9
    return (number, chunk.part or 0, chunk.evidence_id)


class CandidateClaimIndex:
    """후보 특허 1건의 조각 인덱스. IDF 는 후보 내부 조각 집합 기준이다.

    같은 특허의 종속항들이 공유하는 상투 어휘가 자동으로 감쇠되고, 그 청구항만의
    한정 어휘가 부상한다.
    """

    def __init__(self, chunks: list[ClaimChunk]) -> None:
        self._chunks = list(chunks)
        self._tokens = [Counter(tokenize(chunk.text)) for chunk in self._chunks]
        self._lengths = [sum(counter.values()) for counter in self._tokens]
        total = sum(self._lengths)
        self._avg_length = (total / len(self._chunks)) if self._chunks else 1.0
        self._df: Counter[str] = Counter()
        for counter in self._tokens:
            self._df.update(counter.keys())

    def retrieve(self, query: str, *, top_k: int) -> list[ClaimChunk]:
        query_tokens = sorted(set(tokenize(query)))
        if not query_tokens or not self._chunks:
            return []
        scored: list[tuple[float, ClaimChunk]] = []
        n = len(self._chunks)
        for index, chunk in enumerate(self._chunks):
            score = 0.0
            for token in query_tokens:
                frequency = self._tokens[index].get(token, 0)
                if not frequency:
                    continue
                df = self._df[token]
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                normalized = frequency * (_K1 + 1.0) / (
                    frequency
                    + _K1
                    * (1.0 - _B + _B * self._lengths[index] / self._avg_length)
                )
                score += idf * normalized
            if score > 0.0:
                scored.append((round(score, 6), chunk))
        scored.sort(key=lambda item: (-item[0], _chunk_sort_key(item[1])))
        return [chunk for _, chunk in scored[:top_k]]


@dataclass(frozen=True)
class ContextSelection:
    """대조 컨텍스트로 고른 조각들과 선택의 사실 기록."""

    chunks: list[ClaimChunk]
    #: 예산 때문에 **필수 조각**(독립항·앞 3개·초록)을 다 싣지 못했다.
    #: 모델의 자기신고가 아니라 코드가 아는 사실이며, 등급 강등의 입력이 된다.
    incomplete: bool
    #: 검색으로 편입된 조각 ID (관측·진단용).
    retrieved_ids: tuple[str, ...]


def select_context(
    chunks: list[ClaimChunk],
    elements: list[str],
    *,
    top_k: int = 2,
    max_dependent_chunks: int = 12,
    char_budget: int = 8000,
) -> ContextSelection:
    """상위집합 불변식을 지키며 대조 컨텍스트를 조립한다.

    순서(결정론): 독립항 번호순 → 베이스라인 앞 3개의 잔여 → 검색 종속항 번호순
    → 초록. 검색으로 고른 조각은 형제 part 를 동반 편입한다 — "청구항의 일부만
    보았다"는 상태를 만들지 않기 위해서다.
    """
    if not chunks:
        return ContextSelection(chunks=[], incomplete=False, retrieved_ids=())

    claim_chunks = [chunk for chunk in chunks if chunk.claim_number is not None]
    abstract_chunks = [chunk for chunk in chunks if chunk.claim_number is None]

    # 베이스라인이 보던 것: 목록 순서 기준 앞 3개 청구항 (positional — 현행
    # evidence_builder 의 document.claims[:3] 과 같은 집합).
    first_three_numbers: list[int] = []
    for chunk in claim_chunks:
        if chunk.claim_number not in first_three_numbers:
            first_three_numbers.append(chunk.claim_number)  # type: ignore[arg-type]
        if len(first_three_numbers) == 3:
            break
    baseline_numbers = set(first_three_numbers)

    independents = [chunk for chunk in claim_chunks if chunk.independent]
    baseline_rest = [
        chunk
        for chunk in claim_chunks
        if not chunk.independent and chunk.claim_number in baseline_numbers
    ]

    dependents = [
        chunk
        for chunk in claim_chunks
        if not chunk.independent and chunk.claim_number not in baseline_numbers
    ]
    index = CandidateClaimIndex(dependents)
    retrieved_numbers: list[int] = []
    for element in elements:
        for chunk in index.retrieve(element, top_k=top_k):
            if chunk.claim_number not in retrieved_numbers:
                retrieved_numbers.append(chunk.claim_number)  # type: ignore[arg-type]
    # 형제 part 동반 편입 — 청구항 번호 단위로 고른다.
    retrieved = [
        chunk for chunk in dependents if chunk.claim_number in set(retrieved_numbers)
    ]
    retrieved.sort(key=_chunk_sort_key)
    # 상한은 조각 수 기준. 번호순으로 자연히 잘린다 (결정론).
    retrieved = retrieved[:max_dependent_chunks]

    mandatory = [
        *sorted(independents, key=_chunk_sort_key),
        *sorted(baseline_rest, key=_chunk_sort_key),
    ]
    ordered = [*mandatory, *retrieved, *sorted(abstract_chunks, key=_chunk_sort_key)]
    mandatory_ids = {chunk.evidence_id for chunk in mandatory} | {
        chunk.evidence_id for chunk in abstract_chunks
    }

    selected: list[ClaimChunk] = []
    seen: set[str] = set()
    spent = 0
    incomplete = False
    for chunk in ordered:
        if chunk.evidence_id in seen:
            continue
        if spent + len(chunk.text) > char_budget and selected:
            if chunk.evidence_id in mandatory_ids:
                incomplete = True
            continue
        seen.add(chunk.evidence_id)
        selected.append(chunk)
        spent += len(chunk.text)

    return ContextSelection(
        chunks=selected,
        incomplete=incomplete,
        retrieved_ids=tuple(
            chunk.evidence_id for chunk in retrieved if chunk.evidence_id in seen
        ),
    )


__all__ = [
    "CandidateClaimIndex",
    "ContextSelection",
    "INDEX_VERSION",
    "select_context",
    "tokenize",
]
