"""google_drive/models.py 확인. 외부 라이브러리(google-*) 없이 즉시 돌아간다."""

from __future__ import annotations

import dataclasses

import pytest

from ip_risk_agent.connectors.google_drive.models import (
    DRIVE_FILE_SCOPE,
    SELECTABLE_MIME_TYPES,
    DriveChange,
    DriveChangePage,
    DriveFile,
    DriveScopeError,
    normalize_scopes,
    require_exact_drive_file_scope,
)


def test_normalize_scopes_none_returns_empty_set():
    assert normalize_scopes(None) == set()


def test_normalize_scopes_string_splits_on_whitespace():
    assert normalize_scopes("scope-a scope-b") == {"scope-a", "scope-b"}


def test_normalize_scopes_list_passthrough():
    assert normalize_scopes(["scope-a", "scope-b"]) == {"scope-a", "scope-b"}


def test_require_exact_drive_file_scope_passes_for_exact_match():
    require_exact_drive_file_scope({"scope": DRIVE_FILE_SCOPE})


def test_require_exact_drive_file_scope_rejects_extra_scope():
    with pytest.raises(DriveScopeError):
        require_exact_drive_file_scope({"scope": f"{DRIVE_FILE_SCOPE} extra.scope"})


def test_require_exact_drive_file_scope_rejects_missing_scope():
    with pytest.raises(DriveScopeError):
        require_exact_drive_file_scope({})


def test_drive_file_is_frozen():
    file = DriveFile(
        file_id="f1", name="doc", mime_type="text/plain",
        modified_time=None, revision_id=None, web_view_link=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        file.name = "changed"  # type: ignore[misc]


def test_drive_change_page_holds_changes():
    page = DriveChangePage(
        changes=[DriveChange(file_id="f1", removed=False, modified_time="t1", revision_id="1")],
        next_page_token="next",
        new_start_page_token=None,
    )
    assert len(page.changes) == 1
    assert page.changes[0].file_id == "f1"


def test_selectable_mime_types_includes_google_doc():
    assert "application/vnd.google-apps.document" in SELECTABLE_MIME_TYPES
