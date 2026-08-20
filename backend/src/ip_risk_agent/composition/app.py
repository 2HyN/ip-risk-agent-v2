"""FastAPI 애플리케이션 조립.

Control API 는 Agent 1 의 번들 하나로 설치되고, Source 라우터는 provider 설정이
갖춰진 것만 붙는다. 자격증명이 없는 provider 는 **라우트를 만들지 않는다** —
있는 척 열어두고 런타임에 실패하면 원인을 찾기 어렵다.

무엇이 붙었고 무엇이 왜 빠졌는지는 `/health` 가 그대로 보여준다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI

from ip_risk_agent.api import create_control_api_bundle
from ip_risk_agent.application.public_facade import PublicVwsAction
from ip_risk_agent.connectors.github.install_routes import (
    create_github_install_router,
)
from ip_risk_agent.connectors.google_drive.oauth import HttpxDriveOAuthClient
from ip_risk_agent.connectors.google_drive.oauth_routes import (
    create_drive_oauth_router,
)
from ip_risk_agent.connectors.local.routes import create_local_desktop_router

from . import authz
from .container import Container, build_container

# 어떤 provider 라우터가 왜 빠졌는지 사람이 읽을 수 있게 남긴다.
SKIP_REASONS = {
    "google_drive": "GOOGLE_DRIVE_CLIENT_ID/SECRET/REDIRECT_URI 미설정",
    "github": "GITHUB_APP_ID/GITHUB_APP_SLUG 미설정",
}


def _mount_source_routers(app: FastAPI, container: Container) -> dict[str, object]:
    """Source 라우터를 붙이고 무엇을 붙였는지 보고한다."""
    ports = container.source_ports
    registration = container.source_registration
    authorize = container.facade.authorize_vws_action
    mounted: list[str] = []
    skipped: dict[str, str] = {}

    # ── Local: 외부 자격증명이 필요 없다. 항상 붙는다.
    app.include_router(
        create_local_desktop_router(
            staging_store=ports.staging_store,
            change_sink=ports.change_sink,
            device_registration_callback=registration,
            mount_creation_callback=registration,
            # 이 라우터 하나에 resource_id 의미가 다른 라우트 4개가 들어 있다.
            # 경로로 갈라 각자 맞는 스코프를 태운다 (authz.path_scoped 주석 참고).
            authz_dependency=authz.path_scoped(
                {
                    "/desktop/devices/register": authz.session_only(),
                    "/desktop/mounts/register": authz.workspace_scoped(
                        authorize, PublicVwsAction.SOURCE_MOUNT
                    ),
                },
                # staging 과 events 는 resource_id 가 mount_id 다.
                authz.mount_scoped(
                    authorize,
                    PublicVwsAction.MOUNT_SOURCE_OPERATION,
                    container.facade.get_mount_ref,
                ),
            ),
        )
    )
    mounted.append("local")

    # ── Google Drive: OAuth 앱 자격증명이 있어야 의미가 있다.
    source = container.settings.source
    if source.drive_configured:
        app.include_router(
            create_drive_oauth_router(
                client_id=source.drive_client_id or "",
                redirect_uri=source.drive_redirect_uri or "",
                state_store=ports.oauth_state_store,
                oauth_client=HttpxDriveOAuthClient(
                    client_id=source.drive_client_id or "",
                    client_secret=source.drive_client_secret or "",
                    redirect_uri=source.drive_redirect_uri or "",
                ),
                credential_vault=ports.credential_vault,
                connection_creation_callback=registration,
                authz_dependency=authz.workspace_scoped(
                    authorize, PublicVwsAction.SOURCE_MOUNT
                ),
            )
        )
        mounted.append("google_drive:oauth")
    else:
        skipped["google_drive"] = SKIP_REASONS["google_drive"]

    # ── GitHub: App slug 가 있어야 설치 흐름을 시작할 수 있다.
    if source.github_configured:
        app.include_router(
            create_github_install_router(
                app_slug=source.github_app_slug or "",
                state_store=ports.oauth_state_store,
                connection_creation_callback=registration,
                authz_dependency=authz.workspace_scoped(
                    authorize, PublicVwsAction.SOURCE_MOUNT
                ),
            )
        )
        mounted.append("github:install")
    else:
        skipped["github"] = SKIP_REASONS["github"]

    return {"mounted": mounted, "skipped": skipped}


def create_app(
    env: Mapping[str, str] | None = None,
    *,
    container: Container | None = None,
) -> FastAPI:
    """조립된 애플리케이션.

    `container` 를 넘기면 그것을 쓴다. 통합 테스트가 fake OIDC 클라이언트를
    주입할 때 이 경로를 쓴다.
    """
    resolved = container or build_container(env if env is not None else os.environ)

    app = FastAPI(
        title="IP Risk Agent",
        version="0.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.container = resolved

    source_status = _mount_source_routers(app, resolved)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, object]:
        """상태와 함께 '무엇이 실제로 연결되어 있는지'를 돌려준다.

        비밀값은 담지 않는다. 어떤 저장소를 쓰는지, 어떤 provider 라우터가
        붙었는지, 분석 경로가 살아 있는지만 알린다.
        """
        return {
            "status": "ok",
            "control_backend": resolved.backend,
            "google_login": (
                "configured"
                if resolved.settings.control.google_login_configured
                else "unconfigured"
            ),
            "intelligence": (
                "enabled" if resolved.intelligence_enabled else "disabled"
            ),
            "sources": source_status,
        }

    # Control API 는 미들웨어까지 함께 설치하므로 마지막에 붙인다.
    create_control_api_bundle(resolved.control_api).install(app)
    return app


__all__ = ["create_app"]
