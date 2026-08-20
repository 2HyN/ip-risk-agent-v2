"""GitHub App 설치 흐름. Agent2 Spec §16.

Drive OAuth와 달리 code exchange가 없다 — GitHub이 계정/조직/저장소
선택 화면을 전부 처리해주고, 끝나면 installation_id를 콜백으로 준다.
"""

from __future__ import annotations

from urllib.parse import urlencode

GITHUB_APP_INSTALL_URL_TEMPLATE = "https://github.com/apps/{app_slug}/installations/new"


def build_install_url(*, app_slug: str, state: str) -> str:
    query = urlencode({"state": state})
    return f"{GITHUB_APP_INSTALL_URL_TEMPLATE.format(app_slug=app_slug)}?{query}"
