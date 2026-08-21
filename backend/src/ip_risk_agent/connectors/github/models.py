"""GitHub provider-private models 및 GitHubAdapter가 의존하는 최소 계약."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

GITHUB_API_BASE = "https://api.github.com"

CommitFileStatus = Literal["added", "removed", "modified", "renamed", "copied", "changed"]


@dataclass(frozen=True, slots=True)
class GitHubCommitFile:
    filename: str
    status: CommitFileStatus
    previous_filename: str | None


@dataclass(frozen=True, slots=True)
class GitHubCommit:
    sha: str
    files: list[GitHubCommitFile]


@dataclass(frozen=True, slots=True)
class GitHubFileContent:
    path: str
    sha: str
    text: str
    size: int


@dataclass(frozen=True, slots=True)
class GitHubInstallationToken:
    token: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    id: int
    full_name: str
    owner: str
    name: str
    private: bool
    default_branch: str


@dataclass(frozen=True, slots=True)
class GitHubTreeFile:
    path: str
    sha: str


class GitHubProvider(Protocol):
    async def get_installation_token(self) -> GitHubInstallationToken: ...

    async def get_default_branch(self, owner: str, repo: str) -> str: ...

    async def get_commit(self, owner: str, repo: str, sha: str) -> GitHubCommit: ...

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> GitHubFileContent: ...

    async def list_installation_repositories(self) -> list[GitHubRepository]: ...

    async def list_repository_files(
        self, owner: str, repo: str, ref: str
    ) -> list[GitHubTreeFile]: ...
