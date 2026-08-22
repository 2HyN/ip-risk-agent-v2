"""정책 결과에 근거와 설명을 붙인다.

RAG 와 모델은 판정을 바꾸지 못한다. 이미 결정된 결과를 설명할 뿐이다
(Agent 3 Spec 29). 그래서 두 기능이 모두 실패해도 정책 결과는 그대로 남는다.

다만 설명이 빠진 결과로 기존 Risk 를 해소하면 근거 없이 위험이 사라진 것처럼 보인다.
그래서 실패 시 coverage 를 PARTIAL 로 낮춰 자동 해소를 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from iprisk_contracts.common import LicensePolicyOutcome


@dataclass(frozen=True)
class ReferenceChunk:
    """참조 지식 한 조각. RAG corpus 에서 온다."""

    source_id: str
    chunk_id: str
    text: str
    canonical_reference: str
    metadata: dict[str, str] = field(default_factory=dict)


class ReferenceRetriever(Protocol):
    """RAG Engine SDK 를 Analyzer 에서 숨긴다 (Agent 3 Spec 33)."""

    @property
    def corpus_version(self) -> str:
        ...

    async def retrieve(
        self, query: str, *, filters: dict[str, str] | None = None, top_k: int = 3
    ) -> list[ReferenceChunk]:
        ...


def reference_query(license_expression: str, outcome: LicensePolicyOutcome) -> str:
    """검색 질의. 표현식과 분류를 함께 넣어 관련 조항만 좁힌다."""
    return f"{license_expression} 배포 시 의무사항 {outcome.value}"
