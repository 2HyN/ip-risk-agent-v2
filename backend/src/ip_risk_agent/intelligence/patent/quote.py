"""인용 구절의 실재 확인과 위치 계산.

## 왜 필요한가

지금 근거는 **조각 단위**까지 좁혀졌다. 검토 화면은 문단을 보여 줄 수 있지만
"그 안의 어느 문장이 문제인가" 는 아직 가리키지 못한다.

모델에게 인용을 시키면 지어낸다. 그래서 ID 로 가리키게 하고 코드가 대조하는 것이
지금까지의 방식이었다 (Agent 3 Spec 19). 인용도 같은 원칙으로 다룬다 — 모델이 낸
구절이 **본문에 실제로 있는지 코드가 확인**하고, 없으면 그 대조 전체를 버린다.

## 왜 정규화가 필요한가

모델은 줄바꿈을 공백으로 바꾸거나 공백을 다듬어 인용한다. 그대로 비교하면 실재하는
인용도 못 찾는다. 그래서 공백을 하나로 접어 비교하되, **위치는 원문 기준으로**
돌려준다 — 화면이 강조할 대상은 우리가 저장한 원문이기 때문이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")

#: 너무 짧은 인용은 우연히 일치한다. 한 단어짜리 "장치" 같은 것을 위치로 쓰면
#: 하이라이트가 엉뚱한 곳을 짚는다.
MIN_QUOTE_CHARS = 8


@dataclass(frozen=True, slots=True)
class QuoteSpan:
    """원문 기준 위치. 끝은 배타적이다."""

    start: int
    end: int

    def as_metadata(self, prefix: str) -> dict[str, int]:
        return {f"{prefix}_start": self.start, f"{prefix}_end": self.end}


def _fold(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def locate_quote(body: str, quote: str) -> QuoteSpan | None:
    """``quote`` 가 ``body`` 안에 있으면 원문 기준 위치를, 없으면 ``None``.

    공백 차이는 무시하지만 글자는 무시하지 않는다. 지어낸 인용은 찾지 못한다.
    """
    folded_quote = _fold(quote)
    if len(folded_quote) < MIN_QUOTE_CHARS:
        return None

    # 원문의 각 글자가 접힌 문자열에서 어디로 갔는지 기록해 두면, 접힌 좌표를
    # 원문 좌표로 되돌릴 수 있다.
    folded_chars: list[str] = []
    origin: list[int] = []
    previous_space = True
    for index, char in enumerate(body):
        if char.isspace():
            if previous_space:
                continue
            folded_chars.append(" ")
            origin.append(index)
            previous_space = True
            continue
        folded_chars.append(char)
        origin.append(index)
        previous_space = False
    folded_body = "".join(folded_chars).strip()
    # strip 으로 앞에서 잘린 만큼 origin 도 맞춘다.
    leading = len(folded_chars) - len("".join(folded_chars).lstrip())
    origin = origin[leading : leading + len(folded_body)]

    position = folded_body.find(folded_quote)
    if position < 0:
        return None
    start = origin[position]
    end = origin[position + len(folded_quote) - 1] + 1
    return QuoteSpan(start=start, end=end)


__all__ = ["MIN_QUOTE_CHARS", "QuoteSpan", "locate_quote"]
