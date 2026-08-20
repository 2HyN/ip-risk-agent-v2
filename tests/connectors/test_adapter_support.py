"""adapter_support.py의 영수증 헬퍼를 확인한다."""

from __future__ import annotations

from datetime import datetime, timezone

from iprisk_contracts.common import SegmentKind, SourceAccessType, TextSegment

from ip_risk_agent.connectors.common.adapter_support import (
    build_access_receipt,
    bytes_of_segments,
    bytes_of_text,
)


def test_bytes_of_text_ascii():
    assert bytes_of_text("hello") == 5


def test_bytes_of_text_multibyte():
    # 한글 한 글자는 UTF-8에서 3바이트
    assert bytes_of_text("가") == 3


def test_bytes_of_segments_sums_all():
    segments = [
        TextSegment(segment_id="s1", text="hello", segment_kind=SegmentKind.FULL),
        TextSegment(segment_id="s2", text="가나다", segment_kind=SegmentKind.CONTEXT),
    ]
    assert bytes_of_segments(segments) == 5 + 9


def test_bytes_of_segments_empty_list():
    assert bytes_of_segments([]) == 0


def test_build_access_receipt_with_explicit_time():
    fixed_time = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)

    receipt = build_access_receipt(
        SourceAccessType.FULL_CONTENT,
        content_bytes=123,
        provider_request_id="req-1",
        occurred_at=fixed_time,
    )

    assert receipt.access_type is SourceAccessType.FULL_CONTENT
    assert receipt.content_bytes == 123
    assert receipt.provider_request_id == "req-1"
    assert receipt.occurred_at == fixed_time


def test_build_access_receipt_defaults_occurred_at_to_now():
    before = datetime.now(timezone.utc)
    receipt = build_access_receipt(SourceAccessType.METADATA, content_bytes=0)
    after = datetime.now(timezone.utc)

    assert before <= receipt.occurred_at <= after


def test_build_access_receipt_provider_request_id_optional():
    receipt = build_access_receipt(SourceAccessType.DIFF, content_bytes=10)
    assert receipt.provider_request_id is None


def test_build_access_receipt_rejects_negative_content_bytes():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        build_access_receipt(SourceAccessType.METADATA, content_bytes=-1)
