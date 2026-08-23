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


#: 축 값을 질의에 쓸 우리말로. 조항 문서가 우리말이라 값 이름을 그대로 넣으면 맞지 않는다.
_DISTRIBUTION_TERMS = {
    "SAAS": "네트워크 서비스로 제공",
    "BINARY": "바이너리 배포",
    "INTERNAL_ONLY": "사내 전용 사용",
    "LIBRARY_REDISTRIBUTION": "라이브러리 재배포",
    "EMBEDDED": "임베디드 기기 탑재",
}
_LINKING_TERMS = {"DYNAMIC": "동적 링크", "STATIC": "정적 링크"}


def reference_query(
    license_expression: str,
    outcome: LicensePolicyOutcome,
    profile: object | None = None,
) -> str:
    """검색 질의. 표현식과 분류를 함께 넣어 관련 조항만 좁힌다.

    **배포 형태가 질의를 만든다** (§5.7 · §9.2). 같은 LGPL 이라도 정적 링크를 묻는
    것과 동적 링크를 묻는 것은 다른 조항을 찾는다. 축이 질의에 들어가지 않으면
    캐시 키에 축을 넣을 이유도 없어지고, SaaS workspace 의 결과가 사내 전용
    workspace 에 그대로 서빙된다.

    ``profile`` 이 ``None`` 이면 축 없이 만든다. 그 경로는 §5.10 이 이미 막고 있지만
    (설정 전에는 4 단계를 돌리지 않는다) 질의 생성이 그것에 기대지는 않는다.
    """
    parts = [license_expression, "배포 시 의무사항", outcome.value]
    if profile is not None:
        form = getattr(profile, "distribution_form", None)
        linking = getattr(profile, "linking", None)
        modification = getattr(profile, "modification", None)
        redistributes = getattr(profile, "redistributes", None)
        if form is not None:
            parts.append(_DISTRIBUTION_TERMS.get(form.value, form.value))
        if linking is not None and linking.value in _LINKING_TERMS:
            parts.append(_LINKING_TERMS[linking.value])
        if modification is not None:
            parts.append(
                "수정함" if modification.value == "MODIFIED" else "원본 그대로"
            )
        if redistributes is not None:
            parts.append("재배포함" if redistributes else "재배포 안 함")
    return " ".join(parts)
