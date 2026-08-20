"""GitHub artifact identity 인코딩/디코딩.

Agent2 Spec 20번: source_artifact_id = stable logical key(repo_id + branch + path).
resolve_original()이 SourceArtifactRef 하나만 받고 owner/repo/branch/path를
전부 알아야 blob URL을 만들 수 있어서, Local 때와 같은 방식(되돌릴 수 있는
인코딩)을 재사용한다. commit sha는 넣지 않는다 — branch 기준으로 만들면
"현재 revision" URL이 항상 최신을 가리키게 된다.
"""

from __future__ import annotations

import base64

from iprisk_contracts.common import StrictModel

_SEPARATOR = "\x1f"


class GitHubArtifactIdentity(StrictModel):
    owner: str
    repo: str
    branch: str
    path: str


def encode_github_artifact_id(*, owner: str, repo: str, branch: str, path: str) -> str:
    raw = _SEPARATOR.join([owner, repo, branch, path])
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def decode_github_artifact_id(source_artifact_id: str) -> GitHubArtifactIdentity:
    padding = "=" * (-len(source_artifact_id) % 4)
    raw = base64.urlsafe_b64decode((source_artifact_id + padding).encode("ascii")).decode("utf-8")
    parts = raw.split(_SEPARATOR, 3)
    if len(parts) != 4:
        raise ValueError("malformed github artifact id")
    owner, repo, branch, path = parts
    return GitHubArtifactIdentity(owner=owner, repo=repo, branch=branch, path=path)
