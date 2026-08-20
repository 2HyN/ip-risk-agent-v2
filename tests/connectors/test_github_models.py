from __future__ import annotations

import dataclasses

import pytest

from ip_risk_agent.connectors.github.models import (
    GitHubCommit,
    GitHubCommitFile,
    GitHubFileContent,
    GitHubInstallationToken,
)


def test_commit_file_is_frozen():
    f = GitHubCommitFile(filename="a.py", status="modified", previous_filename=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.filename = "b.py"  # type: ignore[misc]


def test_commit_holds_files():
    commit = GitHubCommit(
        sha="abc123",
        files=[GitHubCommitFile(filename="a.py", status="added", previous_filename=None)],
    )
    assert len(commit.files) == 1
    assert commit.files[0].status == "added"


def test_renamed_file_carries_previous_filename():
    f = GitHubCommitFile(filename="new.py", status="renamed", previous_filename="old.py")
    assert f.previous_filename == "old.py"


def test_installation_token_fields():
    token = GitHubInstallationToken(token="ghs_abc", expires_at="2026-08-20T12:00:00Z")
    assert token.token == "ghs_abc"


def test_file_content_fields():
    content = GitHubFileContent(path="src/a.py", sha="deadbeef", text="print(1)", size=8)
    assert content.text == "print(1)"
