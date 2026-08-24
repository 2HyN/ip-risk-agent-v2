"""특허 근거 조각 생성.

전체 특허 문서를 결과에 싣지 않는다 (Agent 3 Spec 17). 청구항과 초록에서 필요한
만큼만 잘라 근거로 남기고, 원문은 출원번호로 되짚게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from iprisk_contracts.common import EvidenceType

from ..common.evidence import EvidenceLedger, patent_abstract_id, patent_claim_id
from .claims import ClaimChunk
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


def _chunk_role(chunk: ClaimChunk) -> str:
    if chunk.claim_number is None:
        return "abstract"
    return "independent" if chunk.independent else "dependent"


def build_rag_evidence(
    document: PatentDocument,
    chunks: list[ClaimChunk],
    ledger: EvidenceLedger,
    *,
    dependencies: dict[int, tuple[int, ...]] | None = None,
) -> PatentEvidenceSet:
    """선별된 청구항·초록 조각을 근거로 등록한다 (rag 대조 전략).

    ID 체계는 기존 그대로다 — ``patent:{번호}:claim:{n}``, 분할 조각만
    ``:part:{k}`` 가 붙는다. 조각은 상한(600자) 이하로 만들어지므로 원장 절단이
    일어나지 않는다 — evidence_truncated 강등의 오발동(긴 초록)이 사라진다.

    청킹이 문서 내용의 순수 함수이므로 같은 청구항이 여러 후보 경로에서 등록돼도
    원장의 "같은 ID 다른 내용" 방어에 걸리지 않는다.
    """
    reference = KIPRIS_REFERENCE.format(application_number=document.application_number)
    deps = dependencies or {}
    evidence_ids: list[str] = []
    types: dict[str, EvidenceType] = {}
    texts: dict[str, str] = {}

    for chunk in chunks:
        role = _chunk_role(chunk)
        metadata: dict[str, str] = {"claim_role": role}
        if chunk.claim_number is not None:
            metadata["claim_number"] = str(chunk.claim_number)
            depends_on = deps.get(chunk.claim_number)
            if depends_on:
                metadata["depends_on"] = ",".join(str(n) for n in depends_on)
        if chunk.part is not None:
            metadata["part"] = str(chunk.part)
        evidence_type = (
            EvidenceType.PATENT_ABSTRACT
            if chunk.claim_number is None
            else EvidenceType.PATENT_CLAIM
        )
        ledger.add(chunk.evidence_id, evidence_type, chunk.text, reference, metadata)
        evidence_ids.append(chunk.evidence_id)
        types[chunk.evidence_id] = evidence_type
        texts[chunk.evidence_id] = chunk.text

    return PatentEvidenceSet(
        application_number=document.application_number,
        evidence_ids=evidence_ids,
        types=types,
        text_by_id=texts,
    )


def render_rag_evidence(
    evidence: PatentEvidenceSet, chunks: list[ClaimChunk]
) -> str:
    """rag 대조용 렌더. 조각마다 (독립항/종속항/초록) 구분을 함께 보여 준다."""
    role_by_id = {chunk.evidence_id: chunk for chunk in chunks}
    lines: list[str] = []
    for evidence_id, text in evidence.text_by_id.items():
        chunk = role_by_id.get(evidence_id)
        if chunk is None or chunk.claim_number is None:
            label = "초록"
        elif chunk.independent:
            label = f"청구항 {chunk.claim_number} · 독립항"
        else:
            label = f"청구항 {chunk.claim_number} · 종속항"
        lines.append(f"[{evidence_id}] ({label})\n{text}")
    return "\n\n".join(lines)
