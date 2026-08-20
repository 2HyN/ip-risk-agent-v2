"""fingerprint.py의 deterministic/collision-safety 성질을 확인한다."""

from __future__ import annotations

import pytest

from ip_risk_agent.connectors.common.fingerprint import (
    compute_fingerprint,
    drive_change_fingerprint,
    github_change_fingerprint,
    local_change_fingerprint,
)


def test_same_input_same_output():
    a = compute_fingerprint("repo", "main", "sha123", "src/x.py")
    b = compute_fingerprint("repo", "main", "sha123", "src/x.py")
    assert a == b


def test_different_input_different_output():
    a = compute_fingerprint("repo", "main", "sha123", "src/x.py")
    b = compute_fingerprint("repo", "main", "sha456", "src/x.py")
    assert a != b


def test_output_is_64_char_hex():
    fp = compute_fingerprint("anything")
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_boundary_concatenation_does_not_collide():
    # "ab"+"c" 와 "a"+"bc" 가 구분자 없이 이어붙이면 똑같은 문자열이 되어버리는
    # 전형적인 실수 케이스. 구분자가 제대로 동작하면 지문이 달라야 한다.
    a = compute_fingerprint("ab", "c")
    b = compute_fingerprint("a", "bc")
    assert a != b


def test_requires_at_least_one_part():
    with pytest.raises(ValueError):
        compute_fingerprint()


def test_github_wrapper_is_deterministic():
    a = github_change_fingerprint(
        repository_id="123", tracked_branch="main", commit_sha="abc", changed_path="src/x.py"
    )
    b = github_change_fingerprint(
        repository_id="123", tracked_branch="main", commit_sha="abc", changed_path="src/x.py"
    )
    assert a == b


def test_drive_wrapper_is_deterministic():
    a = drive_change_fingerprint(file_id="file-1", resolved_revision="v3")
    b = drive_change_fingerprint(file_id="file-1", resolved_revision="v3")
    assert a == b


def test_local_wrapper_is_deterministic():
    a = local_change_fingerprint(
        device_id="dev-1", mount_id="mount-1", relative_path="a/b.py", content_fingerprint="hash1"
    )
    b = local_change_fingerprint(
        device_id="dev-1", mount_id="mount-1", relative_path="a/b.py", content_fingerprint="hash1"
    )
    assert a == b


def test_cross_provider_same_raw_values_do_not_collide():
    # 같은 값이라도 provider tag가 다르면 지문이 달라야 한다.
    drive_fp = drive_change_fingerprint(file_id="X", resolved_revision="Y")
    raw_fp = compute_fingerprint("GOOGLE_DRIVE_TYPO", "X", "Y")
    assert drive_fp != raw_fp  # provider tag 철자 하나만 달라도 완전히 다른 지문


def test_github_and_drive_wrappers_never_collide_by_construction():
    gh = github_change_fingerprint(
        repository_id="X", tracked_branch="Y", commit_sha="Y", changed_path="Y"
    )
    dr = drive_change_fingerprint(file_id="X", resolved_revision="Y")
    assert gh != dr
