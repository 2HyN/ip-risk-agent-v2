"""Evidence 수집기.

``AnalysisResult`` 는 candidate 가 참조하는 evidence ID 가 실제로 존재할 것을
요구한다. 그 관계를 손으로 맞추면 반드시 어긋나므로, 등록과 참조를 한 곳에서 처리한다.

ID 는 사람이 읽을 수 있는 형태로 만든다. 로그에서 어떤 근거였는지 되짚을 수 있어야
모델이 지어낸 참조를 발견할 수 있다 (Agent 3 Spec 38).
"""

from __future__ import annotations

from iprisk_contracts.common import Evidence, EvidenceType, SafeMetadata

# 근거는 재검토를 위한 최소 인용이지 원문 보관이 아니다 (Blueprint 29).
MAX_EXCERPT_CHARS = 600


def source_segment_id(segment_id: str) -> str:
    return f"src:{segment_id}"


def patent_claim_id(application_number: str, claim_number: int) -> str:
    return f"patent:{application_number}:claim:{claim_number}"


def patent_abstract_id(application_number: str) -> str:
    return f"patent:{application_number}:abstract"


def package_metadata_id(ecosystem: str, package: str, version: str | None) -> str:
    return f"pkg:{ecosystem}:{package}:{version or 'unresolved'}"


def rag_chunk_id(source_id: str, chunk: str) -> str:
    return f"rag:{source_id}:{chunk}"


def truncate(text: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    """인용을 최대 길이로 자른다. 잘렸다는 사실이 보이도록 말줄임표를 남긴다."""
    collapsed = text.strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


class EvidenceLedger:
    """한 번의 분석 안에서 evidence 를 모으고 ID 중복을 막는다."""

    def __init__(self, excerpt_limit: int = MAX_EXCERPT_CHARS) -> None:
        self._items: dict[str, Evidence] = {}
        self._excerpt_limit = excerpt_limit

    def add(
        self,
        evidence_id: str,
        evidence_type: EvidenceType,
        excerpt: str,
        reference: str,
        metadata_safe: SafeMetadata | None = None,
    ) -> str:
        """근거를 등록하고 ID 를 돌려준다.

        같은 ID 를 다시 등록하는 것은 정상이다. 하나의 특허 청구항이 여러 후보에서
        인용될 수 있다. 다만 같은 ID 로 다른 내용을 넣으려 하면 ID 설계가 잘못된
        것이므로 막는다.
        """
        prepared = Evidence(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            excerpt=truncate(excerpt, self._excerpt_limit),
            reference=reference,
            metadata_safe=dict(metadata_safe or {}),
        )
        existing = self._items.get(evidence_id)
        if existing is not None and existing != prepared:
            raise ValueError(
                f"evidence_id {evidence_id!r} was reused with different content"
            )
        self._items[evidence_id] = prepared
        return evidence_id

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self._items

    def require(self, evidence_ids: list[str]) -> list[str]:
        """참조가 전부 등록되어 있는지 확인한다. 모델 출력 검증에 쓴다."""
        missing = [eid for eid in evidence_ids if eid not in self._items]
        if missing:
            raise ValueError(f"unknown evidence IDs: {sorted(missing)}")
        return evidence_ids

    def items(self) -> list[Evidence]:
        """등록 순서를 유지해 돌려준다. 결과가 실행마다 흔들리지 않아야 한다."""
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
