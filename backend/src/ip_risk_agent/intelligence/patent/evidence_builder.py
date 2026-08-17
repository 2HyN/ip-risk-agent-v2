"""특허 근거 조각 생성.

전체 특허 문서를 결과에 싣지 않는다 (Agent 3 Spec 17). 청구항과 초록에서 필요한
만큼만 잘라 근거로 남기고, 원문은 출원번호로 되짚게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts.common import EvidenceType

from ..common.evidence import EvidenceLedger, patent_abstract_id, patent_claim_id
from .kipris import PatentDocument

KIPRIS_REFERENCE = "KIPRIS Plus 출원번호 {application_number}"


@dataclass(frozen=True)
class PatentEvidenceSet:
    """한 특허에서 뽑은 근거들."""

    application_number: str
    evidence_ids: list[str]
    types: dict[str, EvidenceType]
    text_by_id: dict[str, str]

    @property
    def is_empty(self) -> bool:
        return not self.evidence_ids


def build_patent_evidence(
    document: PatentDocument,
    ledger: EvidenceLedger,
    *,
    max_claims: int = 3,
) -> PatentEvidenceSet:
    """청구항을 우선하고 초록을 보조로 등록한다.

    청구항이 권리 범위를 정하는 부분이므로 대조 가치가 더 크다. 다만 KIPRIS 가
    제공하는 것은 대개 초록뿐이라 실제로는 초록만 남는 경우가 많다.
    """
    reference = KIPRIS_REFERENCE.format(application_number=document.application_number)
    evidence_ids: list[str] = []
    types: dict[str, EvidenceType] = {}
    texts: dict[str, str] = {}

    for index, claim in enumerate(document.claims[:max_claims], start=1):
        if not claim.strip():
            continue
        evidence_id = patent_claim_id(document.application_number, index)
        ledger.add(
            evidence_id,
            EvidenceType.PATENT_CLAIM,
            claim,
            reference,
            {"claim_number": str(index)},
        )
        evidence_ids.append(evidence_id)
        types[evidence_id] = EvidenceType.PATENT_CLAIM
        texts[evidence_id] = claim

    if document.abstract.strip():
        evidence_id = patent_abstract_id(document.application_number)
        ledger.add(
            evidence_id,
            EvidenceType.PATENT_ABSTRACT,
            document.abstract,
            reference,
            dict(document.metadata),
        )
        evidence_ids.append(evidence_id)
        types[evidence_id] = EvidenceType.PATENT_ABSTRACT
        texts[evidence_id] = document.abstract

    return PatentEvidenceSet(
        application_number=document.application_number,
        evidence_ids=evidence_ids,
        types=types,
        text_by_id=texts,
    )


def render_evidence(evidence: PatentEvidenceSet) -> str:
    """모델 입력용. ID 를 함께 보여 그 ID 로만 답하게 한다."""
    return "\n\n".join(
        f"[{evidence_id}]\n{text}" for evidence_id, text in evidence.text_by_id.items()
    )
