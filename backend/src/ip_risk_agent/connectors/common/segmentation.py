"""문서를 검토 단위로 나눈다.

지금까지 세 커넥터가 모두 문서를 통짜 하나(``segment_id="full"``)로 넘겼다. 그
결과 특허 대조가 만들 수 있는 것은 (문서 전체 × 청구항) 쌍뿐이었고, Risk 에 남는
원문 근거는 **매칭된 부분이 아니라 파일 앞부분 600 자**였다. 실측에서 특허 Risk
33 건이 모두 ``src:full`` 하나만 인용했다.

## 무엇을 한 조각으로 보는가

문단 단위로 고정하지 않는다. 목표는 두 가지를 동시에 만족하는 조각이다.

* **문맥으로 읽을 수 있을 만큼 크다.** 원문은 저장하지 않으므로 검토 화면이
  보여줄 문맥은 이 조각 자체다. 조각이 한 줄이면 사람이 판단할 수 없다.
* **가리킬 수 있을 만큼 작다.** 조각 전체가 근거로 남으므로, 너무 크면 "이 문서
  어딘가" 와 다를 바 없다.

그래서 빈 줄로 갈린 블록을 기본으로 삼되, 너무 작은 블록은 앞에 붙이고 너무 큰
블록은 문장 경계에서 자른다. 코드 울타리(``` )는 안에서 자르지 않는다 — 잘린
코드는 문맥이 되지 못한다.

## 줄 번호

``TextSegment`` 는 처음부터 ``line_start`` / ``line_end`` 를 갖고 있었다.
커넥터가 채우지 않았을 뿐이다. 채워 두면 나중에 "문서의 어느 줄/문장" 을 짚는
하이라이트가 이 값 위에 얹힌다.

## segment_id

``L{start}-{end}`` 로 둔다. 사람이 읽을 수 있고 문서 안에서 겹치지 않는다.
개정 사이에 안정적이지는 않지만(줄이 밀리면 바뀐다) 근거 행은 분석 실행마다 새로
쓰이므로(``risk_evidence_id_for`` 가 analysis_job_id 를 포함한다) 이력이 끊기지
않는다. 위치를 그대로 읽을 수 있다는 이점이 더 크다.
"""

from __future__ import annotations

import re

from iprisk_contracts.common import ArtifactKind, SegmentKind, TextSegment

from ...core.artifacts.dependency_files import DEPENDENCY_KINDS

#: 이보다 작은 블록은 앞 조각에 붙인다. 한두 줄짜리 조각은 문맥이 되지 못한다.
MIN_SEGMENT_CHARS = 160

#: 이보다 큰 조각은 문장 경계에서 자른다. 근거 원장이 600 자에서 잘라내므로
#: (``MAX_EXCERPT_CHARS``) 그 안에 들어와야 검토 화면이 조각 전체를 볼 수 있다.
MAX_SEGMENT_CHARS = 600

#: Security Gate 가 64 개에서 자르고 그때 content scope 를 낮춘다. 그 앞에서
#: 미리 줄여 두면 큰 문서가 조용히 부분 분석이 되는 것을 피할 수 있다.
MAX_SEGMENTS = 64

_FENCE = re.compile(r"^\s*(```|~~~)")
_SENTENCE_END = re.compile(r"(?<=[.!?。？！])\s+|(?<=다\.)\s+|\n")


def whole_document(text: str) -> list[TextSegment]:
    """통짜 한 조각. 나누면 읽을 수 없게 되는 문서에 쓴다."""
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return []
    return [
        TextSegment(
            segment_id="full",
            text=text,
            line_start=1,
            line_end=max(len(lines), 1),
            segment_kind=SegmentKind.FULL,
        )
    ]


def segments_for(text: str, artifact_kind: ArtifactKind) -> list[TextSegment]:
    """종류에 맞는 조각을 만든다. 커넥터는 이것을 부른다.

    ## 왜 종류를 봐야 하는가

    조각화는 **산문**을 위해 만들어졌다. 특허 대조가 "이 문서 어딘가" 가 아니라 매칭된
    문단을 가리킬 수 있게 하려는 것이다. 그런데 세 커넥터가 종류를 가리지 않고 적용해서
    **의존성 파일까지 조각났다.**

    의존성 파일은 나누면 읽을 수 없다. 파서는 조각마다 따로 도는데, ``pyproject.toml``
    을 빈 줄에서 자르면 ``[project]`` 표 밖에 떨어진 줄은 어느 표에 속했는지 알 수 없고,
    ``package.json`` 을 자르면 그냥 깨진 JSON 이다. 실측이 그대로다.

    ```
    pyproject.toml   통짜 20 건  →  조각 경유 3 건
    package.json     통짜  1 건  →  조각 경유 0 건
    ```

    그리고 0 건은 실패가 아니라 ``SUCCEEDED`` + ``COMPLETE`` 로 올라가 **기존 Risk 를
    해소한다.** 위험을 놓치는 것이 아니라 사라졌다고 오보하는 것이다.

    ## 잃는 것

    의존성 파일에서는 줄 단위 근거를 못 가리킨다. 아깝지 않다 — 그쪽 근거는 원문 인용이
    아니라 **패키지와 라이선스**이고, 그것은 파서가 이미 정확히 안다. 조각으로 얻을 것이
    애초에 없었다.
    """
    if artifact_kind in DEPENDENCY_KINDS:
        return whole_document(text)
    return split_document(text)


def split_document(text: str) -> list[TextSegment]:
    """문서를 검토 단위 조각으로 나눈다. 빈 문서면 빈 목록을 돌려준다.

    산문과 소스 코드에만 쓴다. 의존성 파일은 :func:`whole_document` 로 간다 —
    고르는 것은 :func:`segments_for` 다.
    """
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        return []

    blocks = _blocks(lines)
    merged = _merge_small(blocks)
    pieces: list[tuple[int, int, str]] = []
    for start, end, body in merged:
        pieces.extend(_split_large(start, end, body))

    if len(pieces) > MAX_SEGMENTS:
        pieces = _fold_to_limit(pieces)

    # 한 블록이 여러 조각으로 갈리면 줄 범위가 같아진다. 그대로 두면 segment_id 가
    # 겹치고, 근거 원장은 같은 ID 에 다른 내용이 오는 것을 거부한다. 같은 범위가
    # 두 번째부터는 순번을 붙인다.
    seen: dict[tuple[int, int], int] = {}
    segments: list[TextSegment] = []
    for start, end, body in pieces:
        if not body.strip():
            continue
        occurrence = seen.get((start, end), 0) + 1
        seen[(start, end)] = occurrence
        suffix = "" if occurrence == 1 else f"#{occurrence}"
        segments.append(
            TextSegment(
                segment_id=f"L{start}-{end}{suffix}",
                text=body,
                line_start=start,
                line_end=end,
                segment_kind=SegmentKind.FULL,
            )
        )
    return segments


def _blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    """빈 줄로 갈린 블록. 코드 울타리 안은 한 덩어리로 유지한다."""
    blocks: list[tuple[int, int, str]] = []
    current: list[str] = []
    start = 1
    in_fence = False
    for index, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            if not current:
                start = index
            current.append(line)
            continue
        if not in_fence and not line.strip():
            if current:
                blocks.append((start, index - 1, "\n".join(current)))
                current = []
            continue
        if not current:
            start = index
        current.append(line)
    if current:
        blocks.append((start, len(lines), "\n".join(current)))
    return blocks


def _merge_small(blocks: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """작은 블록을 앞에 붙인다. 붙여도 상한을 넘지 않을 때만 붙인다."""
    merged: list[tuple[int, int, str]] = []
    for start, end, body in blocks:
        if not merged:
            merged.append((start, end, body))
            continue
        previous_start, _previous_end, previous_body = merged[-1]
        combined = f"{previous_body}\n\n{body}"
        too_small = len(previous_body) < MIN_SEGMENT_CHARS or len(body) < MIN_SEGMENT_CHARS
        if too_small and len(combined) <= MAX_SEGMENT_CHARS:
            merged[-1] = (previous_start, end, combined)
        else:
            merged.append((start, end, body))
    return merged


def _split_large(start: int, end: int, body: str) -> list[tuple[int, int, str]]:
    """상한을 넘는 조각을 문장 경계에서 자른다.

    줄 번호는 자른 조각마다 다시 셀 수 없으므로 원래 범위를 그대로 물려준다.
    조각을 더 정확히 짚는 것은 나중에 문장 단위 하이라이트가 할 일이고, 여기서는
    프롬프트와 근거가 감당할 크기로 만드는 것이 목적이다.
    """
    if len(body) <= MAX_SEGMENT_CHARS:
        return [(start, end, body)]
    parts: list[tuple[int, int, str]] = []
    buffer = ""
    for sentence in _SENTENCE_END.split(body):
        if not sentence:
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) > MAX_SEGMENT_CHARS and buffer:
            parts.append((start, end, buffer))
            buffer = sentence
        else:
            buffer = candidate
    if buffer:
        parts.append((start, end, buffer))

    # 문장 경계가 없는 덩어리(표 한 줄, 긴 코드 블록)는 위에서 줄지 않는다. 상한을
    # 넘긴 채로 두면 근거 원장이 뒤를 잘라내고, 잘린 뒤쪽은 검토 화면에 영영
    # 나타나지 않는다. 하이라이트가 그 부분을 짚어야 할 때 보여 줄 것이 없다.
    # 그래서 마지막에는 길이로 자른다. 버리는 것보다 낫다.
    bounded: list[tuple[int, int, str]] = []
    for piece_start, piece_end, text in parts or [(start, end, body)]:
        while len(text) > MAX_SEGMENT_CHARS:
            bounded.append((piece_start, piece_end, text[:MAX_SEGMENT_CHARS]))
            text = text[MAX_SEGMENT_CHARS:]
        if text:
            bounded.append((piece_start, piece_end, text))
    return bounded


def _fold_to_limit(pieces: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """개수 상한에 맞춰 뒤쪽부터 이웃과 합친다.

    잘라 버리지 않는다. 뒤를 버리면 문서 후반이 조용히 분석에서 빠진다.
    """
    folded = list(pieces)
    while len(folded) > MAX_SEGMENTS:
        merged: list[tuple[int, int, str]] = []
        for piece in folded:
            if merged and len(merged) + (len(folded) - folded.index(piece)) > MAX_SEGMENTS:
                start, _end, body = merged[-1]
                merged[-1] = (start, piece[1], f"{body}\n\n{piece[2]}")
            else:
                merged.append(piece)
        if len(merged) == len(folded):  # pragma: no cover - 방어적 종료
            break
        folded = merged
    return folded


__all__ = [
    "MAX_SEGMENTS",
    "MAX_SEGMENT_CHARS",
    "MIN_SEGMENT_CHARS",
    "segments_for",
    "split_document",
    "whole_document",
]
