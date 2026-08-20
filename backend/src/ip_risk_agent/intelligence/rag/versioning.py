"""corpus 버전.

과거 판단과 현재 판단이 왜 다른지 설명하려면 그때 어떤 지식으로 답했는지 알아야 한다
(Blueprint 30). 그래서 corpus 버전을 결과에 남긴다.

형식은 ``YYYY-MM-DD.N`` 이다. 같은 날 여러 번 갱신할 수 있어 일련번호를 붙인다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERSION_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\.(?P<serial>\d+)$")


class InvalidCorpusVersion(ValueError):
    """버전 문자열이 형식에 맞지 않는다."""


@dataclass(frozen=True, order=True)
class CorpusVersion:
    """비교 가능한 corpus 버전."""

    date: str
    serial: int

    @classmethod
    def parse(cls, raw: str) -> "CorpusVersion":
        match = VERSION_PATTERN.match(raw or "")
        if not match:
            raise InvalidCorpusVersion(
                f"expected YYYY-MM-DD.N, got {raw!r}"
            )
        return cls(date=match.group("date"), serial=int(match.group("serial")))

    def bump(self) -> "CorpusVersion":
        """같은 날 다시 올릴 때. 날짜가 바뀌면 호출부가 새로 만든다."""
        return CorpusVersion(self.date, self.serial + 1)

    def __str__(self) -> str:
        return f"{self.date}.{self.serial}"
