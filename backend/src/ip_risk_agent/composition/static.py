"""빌드된 Web UI 를 API 와 같은 origin 에서 서빙한다.

프론트엔드는 production 번들에서 **상대 경로로 `/api/v1` 을 호출**한다
(`ApiClient` 의 `baseUrl` 기본값이 빈 문자열이다). 그래서 별도 호스트에 올리면
그 호스트의 `/api/v1` 을 찾아 전부 실패한다. 하드닝 설정도 `APP_PUBLIC_BASE_URL`
하나만 CORS origin 으로 허용한다. 즉 이 구조에서 same-origin 서빙은 선택이
아니라 전제다.

가장 조심할 것은 **SPA fallback 이 API 경로를 삼키는 것**이다. 그렇게 되면
API 호출이 404 대신 HTML 을 받아, 프론트엔드에서 "JSON 파싱 실패"로만 보이고
원인을 찾기 어려워진다. 그래서 예약 접두사를 명시적으로 막는다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# index.html 은 절대 캐시하지 않는다. 자산 파일명에는 해시가 붙어 바뀌지만
# index.html 의 경로는 고정이다. 브라우저가 옛 index.html 을 들고 있으면 이미
# 사라진 해시 파일을 찾아 흰 화면이 되거나, 옛 코드가 그대로 돌아 배포가
# 반영되지 않은 것처럼 보인다.
NO_STORE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

# 이 접두사로 시작하는 경로는 SPA 로 넘기지 않는다.
# 여기에 해당하는데 실제 라우트가 없으면 정직하게 404 를 돌려준다.
RESERVED_PREFIXES: tuple[str, ...] = (
    "api/",
    "webhooks/",
    "desktop/",
    "internal/",
    "docs",
    "redoc",
    "openapi.json",
    "health",
)


def is_reserved(path: str) -> bool:
    """API 소유 경로인지. SPA fallback 이 가로채면 안 되는 것들이다."""
    normalized = path.lstrip("/")
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in RESERVED_PREFIXES
    )


def sources_path(
    risk_workspace_id: str,
    connection_id: str | None = None,
    provider: str | None = None,
) -> str:
    """Source 연결을 마친 뒤 브라우저를 돌려보낼 SPA 경로.

    연결만 만들어진 상태로는 아직 감시할 대상이 정해지지 않았다. 화면이
    저장소·폴더 선택으로 이어가려면 **어떤 연결인지** 알아야 하므로 함께
    싣는다. id 를 그대로 끼워 넣으면 경로·질의 구분자가 섞일 수 있어
    인코딩한다.
    """
    path = f"/w/{quote(risk_workspace_id, safe='')}/sources"
    params = [
        (name, value)
        for name, value in (("connection", connection_id), ("provider", provider))
        if value
    ]
    if not params:
        return path
    query = "&".join(f"{name}={quote(value, safe='')}" for name, value in params)
    return f"{path}?{query}"


def connected_redirect(provider: str) -> Callable[[str, str], str]:
    """provider 콜백이 끝난 뒤 돌아갈 곳을 만든다."""

    def redirect(risk_workspace_id: str, connection_id: str) -> str:
        return sources_path(risk_workspace_id, connection_id, provider)

    return redirect


def install_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """빌드 산출물을 서빙한다. 디렉터리가 없으면 아무것도 하지 않는다.

    **반드시 모든 API 라우터를 등록한 뒤에 호출해야 한다.** Starlette 는 등록
    순서대로 매칭하므로, 먼저 붙이면 catch-all 이 API 를 가린다.
    """
    index = dist_dir / "index.html"
    if not index.is_file():
        return False

    assets = dist_dir / "assets"
    if assets.is_dir():
        # 해시가 붙은 번들이라 오래 캐시해도 안전하다.
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if is_reserved(full_path):
            # API 경로인데 여기까지 왔다는 것은 그런 라우트가 없다는 뜻이다.
            # HTML 을 돌려주면 호출부가 원인을 알 수 없게 된다.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        # 정적 파일이 실제로 있으면 그것을, 아니면 index.html 을 준다.
        # 클라이언트 라우팅(예: /w/{id}/risks)이 새로고침에도 동작해야 한다.
        candidate = (dist_dir / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(dist_dir.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(index, headers=NO_STORE)

    return True


__all__ = [
    "NO_STORE",
    "RESERVED_PREFIXES",
    "install_frontend",
    "is_reserved",
    "connected_redirect",
    "sources_path",
]
