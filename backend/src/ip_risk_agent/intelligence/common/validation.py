"""입력 검증과 인용 대조.

Security Gate 는 Control Plane 이 이미 통과시켰지만, Analyzer 도 한 번 더 확인한다
(Agent 3 Spec 5, defense in depth). Gate 가 잘못 동작했을 때 원문이 외부 provider 로
나가는 것을 여기서 막는 것이 목적이다.
"""

from __future__ import annotations

import re

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.common import AnalysisType

from .errors import ArtifactRejectedError

_WHITESPACE = re.compile(r"\s+")


def normalize_quote(text: str) -> str:
    """공백 차이를 무시하고 비교하기 위한 정규화.

    모델은 줄바꿈과 들여쓰기를 임의로 바꿔 인용한다. 그것까지 불일치로 보면
    실제로 원문에 있는 인용까지 버리게 된다.
    """
    return _WHITESPACE.sub(" ", text).strip()


def quote_exists(quote: str, haystack: str) -> bool:
    """인용문이 원문에 실제로 존재하는지. 빈 인용은 근거로 인정하지 않는다."""
    normalized = normalize_quote(quote)
    return bool(normalized) and normalized in normalize_quote(haystack)


def validate_artifact(artifact: AnalysisArtifact, analysis_type: AnalysisType) -> None:
    """Analyzer 진입 전 공통 검증. 통과하지 못하면 provider 를 호출하지 않는다."""
    if artifact.contract_version != "1":
        raise ArtifactRejectedError(
            f"unsupported contract version: {artifact.contract_version!r}"
        )

    # 이 검사가 이 함수의 존재 이유다. 나머지는 부수적인 무결성 확인이다.
    if not artifact.security_context.approved:
        raise ArtifactRejectedError(
            "artifact has not passed the Security Gate; refusing to call any provider"
        )

    for field in ("analysis_job_id", "artifact_id", "revision"):
        if not getattr(artifact, field):
            raise ArtifactRejectedError(f"{field} must not be empty")

    if analysis_type not in artifact.requested_analyzers:
        raise ArtifactRejectedError(
            f"{analysis_type.value} was not requested for this artifact"
        )

    seen: set[str] = set()
    for segment in artifact.text_segments:
        if not segment.segment_id:
            raise ArtifactRejectedError("text segment is missing segment_id")
        if segment.segment_id in seen:
            raise ArtifactRejectedError(
                f"duplicate segment_id: {segment.segment_id!r}"
            )
        seen.add(segment.segment_id)
