"""Deterministic segment selection and byte-bounded minimization."""

from __future__ import annotations

from iprisk_contracts import (
    ArtifactKind,
    ContentScope,
    SegmentKind,
    TextSegment,
)

from .policy import SecurityGatePolicy


def minimize_segments(
    *,
    artifact_kind: ArtifactKind,
    content_scope: ContentScope,
    segments: list[TextSegment],
    source_byte_size: int,
    policy: SecurityGatePolicy,
) -> tuple[list[TextSegment], ContentScope]:
    selected = list(segments)
    if artifact_kind is ArtifactKind.SOURCE_CODE:
        changed = [
            segment for segment in segments if segment.segment_kind is SegmentKind.CHANGED
        ]
        context = [
            segment for segment in segments if segment.segment_kind is SegmentKind.CONTEXT
        ]
        selected = changed + context if changed or context else selected
    elif artifact_kind in {ArtifactKind.DOCUMENT_TEXT, ArtifactKind.TEXT}:
        if source_byte_size > policy.document_full_text_bytes:
            changed = [
                segment
                for segment in segments
                if segment.segment_kind is SegmentKind.CHANGED
            ]
            context = [
                segment
                for segment in segments
                if segment.segment_kind is SegmentKind.CONTEXT
            ]
            if changed or context:
                selected = changed + context

    output: list[TextSegment] = []
    remaining = policy.max_output_bytes
    minimized = len(selected) != len(segments)
    for segment in selected[: policy.max_segments]:
        segment_limit = min(policy.max_segment_bytes, remaining)
        if segment_limit < 1:
            minimized = True
            break
        text, truncated = _truncate_utf8(segment.text, segment_limit)
        if not text and segment.text:
            minimized = True
            continue
        output.append(
            TextSegment(
                segment_id=segment.segment_id,
                text=text,
                line_start=segment.line_start,
                line_end=segment.line_end,
                segment_kind=segment.segment_kind,
            )
        )
        remaining -= len(text.encode("utf-8"))
        minimized = minimized or truncated
    if len(selected) > policy.max_segments:
        minimized = True
    effective_scope = (
        ContentScope.CHANGESET_WITH_CONTEXT if minimized else content_scope
    )
    return output, effective_scope


def _truncate_utf8(value: str, byte_limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value, False
    truncated = encoded[:byte_limit]
    while truncated:
        try:
            return truncated.decode("utf-8"), True
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "", True


__all__ = ["minimize_segments"]
