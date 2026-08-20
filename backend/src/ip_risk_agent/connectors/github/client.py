"""GitHubAppProvider: 실제 GitHub API를 호출하는 client 구현.

PAT 대신 GitHub App 인증을 쓴다 (Agent2 Spec 15번) — 앱 private key로
서명한 JWT(최대 10분 유효)로 installation access token을 발급받고,
그 토큰을 Bearer로 실제 API를 호출한다.

get_file_content/get_default_branch 패턴은 dsdr-re/AI_develop_5(개인 저장소)
services/github_client.py에서 참고했다 (그 코드는 PAT를 썼지만, 토큰 발급과
API 호출 자체는 분리돼 있어 로직만 재사용).
"""

from __future__ import annotations

import base64
import time

import httpx
import jwt

from .error_mapping import map_github_status_code
from .models import (
    GITHUB_API_BASE,
    GitHubCommit,
    GitHubCommitFile,
    GitHubFileContent,
    GitHubInstallationToken,
    GitHubRepository,
)


def build_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


class GitHubAppProvider:
    def __init__(self, *, app_id: str, private_key_pem: str, installation_id: str) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._installation_id = installation_id

    async def get_installation_token(self) -> GitHubInstallationToken:
        app_jwt = build_app_jwt(self._app_id, self._private_key_pem)
        url = f"{GITHUB_API_BASE}/app/installations/{self._installation_id}/access_tokens"
        headers = {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers)
        if resp.status_code >= 400:
            raise map_github_status_code(resp.status_code, "failed to obtain installation token")
        data = resp.json()
        return GitHubInstallationToken(token=data["token"], expires_at=data["expires_at"])

    async def get_default_branch(self, owner: str, repo: str) -> str:
        token = await self.get_installation_token()
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._auth_headers(token.token))
        if resp.status_code >= 400:
            raise map_github_status_code(resp.status_code, "failed to fetch repository metadata")
        return resp.json().get("default_branch") or "main"

    async def get_commit(self, owner: str, repo: str, sha: str) -> GitHubCommit:
        token = await self.get_installation_token()
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{sha}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._auth_headers(token.token))
        if resp.status_code >= 400:
            raise map_github_status_code(resp.status_code, "failed to fetch commit")
        data = resp.json()
        files = [
            GitHubCommitFile(
                filename=f["filename"],
                status=f["status"],
                previous_filename=f.get("previous_filename"),
            )
            for f in data.get("files", [])
        ]
        return GitHubCommit(sha=data["sha"], files=files)

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> GitHubFileContent:
        token = await self.get_installation_token()
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._auth_headers(token.token), params={"ref": ref})
        if resp.status_code >= 400:
            raise map_github_status_code(resp.status_code, "failed to fetch file content")
        data = resp.json()
        content_b64 = data.get("content", "")
        text = base64.b64decode(content_b64).decode("utf-8", errors="replace") if content_b64 else ""
        return GitHubFileContent(path=path, sha=data.get("sha", ""), text=text, size=data.get("size", 0))

    @staticmethod
    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    async def list_installation_repositories(self) -> list[GitHubRepository]:
        """이 installation이 접근 가능한 저장소 목록을 가져온다.

        MVP는 단일 페이지(최대 100개)만 처리한다 — 한 installation에
        저장소가 100개를 넘는 경우는 페이지네이션 추가가 필요하다
        (known limitation으로 문서화함)."""

        token = await self.get_installation_token()
        url = f"{GITHUB_API_BASE}/installation/repositories"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url, headers=self._auth_headers(token.token), params={"per_page": 100}
            )
        if resp.status_code >= 400:
            raise map_github_status_code(resp.status_code, "failed to list installation repositories")
        data = resp.json()
        return [
            GitHubRepository(
                id=repo["id"],
                full_name=repo["full_name"],
                owner=repo["owner"]["login"],
                name=repo["name"],
                private=repo["private"],
                default_branch=repo.get("default_branch") or "main",
            )
            for repo in data.get("repositories", [])
        ]


class GitHubAppProviderFactory:
    def __init__(self, *, app_id: str, private_key_pem: str) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem

    def create(self, installation_id: str) -> GitHubAppProvider:
        return GitHubAppProvider(
            app_id=self._app_id,
            private_key_pem=self._private_key_pem,
            installation_id=installation_id,
        )
