"""SourceAdapter 공통 유틸: 영수증(SourceAccessReceipt) 생성 도우미.

Master Spec 11번 SourceAccessReceipt / Agent 2 Spec 41번을 그대로 감싼
얇은 헬퍼. 새 개념은 없다 — adapter(B/C/D)가 매번 같은 보일러플레이트를
반복하지 않도록 하는 편의 함수다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from iprisk_contracts.common import SourceAccessReceipt, SourceAccessType, TextSegment


def bytes_of_text(text: str) -> int:
    """문자열의 실제 UTF-8 바이트 크기. content_bytes 계산에 쓴다."""

    return len(text.encode("utf-8"))


def bytes_of_segments(segments: list[TextSegment]) -> int:
    """여러 TextSegment의 총 바이트 크기 합."""

    return sum(bytes_of_text(segment.text) for segment in segments)


def build_access_receipt(
    access_type: SourceAccessType,
    *,
    content_bytes: int,
    provider_request_id: str | None = None,
    occurred_at: datetime | None = None,
) -> SourceAccessReceipt:
    """SourceAccessReceipt를 만든다. occurred_at을 안 주면 호출 시점(UTC)을 쓴다."""

    return SourceAccessReceipt(
        access_type=access_type,
        provider_request_id=provider_request_id,
        content_bytes=content_bytes,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
