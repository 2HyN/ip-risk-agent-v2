"""FastAPI 애플리케이션 조립.

Control API 는 Agent 1 의 번들 하나로 설치되고, Source 라우터는 provider 설정이
갖춰진 것만 붙는다. 자격증명이 없는 provider 는 **라우트를 만들지 않는다** —
있는 척 열어두고 런타임에 실패하면 원인을 찾기 어렵다.

무엇이 붙었고 무엇이 왜 빠졌는지는 `/health` 가 그대로 보여준다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI

from ip_risk_agent.api import create_control_api_bundle
from ip_risk_agent.application.public_facade import PublicVwsAction
from ip_risk_agent.connectors.github.install_routes import (
    create_github_install_router,
)
from ip_risk_agent.connectors.github.mounts_routes import create_github_mounts_router
from ip_risk_agent.connectors.github.routes import create_github_webhook_router
from ip_risk_agent.connectors.google_drive.mounts_routes import (
    create_drive_mounts_router,
)
from ip_risk_agent.connectors.google_drive.oauth import HttpxDriveOAuthClient
from ip_risk_agent.connectors.google_drive.oauth_routes import (
    create_drive_oauth_router,
)
from ip_risk_agent.connectors.google_drive.routes import create_drive_webhook_router
from ip_risk_agent.connectors.local.routes import create_local_desktop_router

from . import authz
from .container import Container, build_container
from .static import connected_redirect, install_frontend

# 어떤 provider 라우터가 왜 빠졌는지 사람이 읽을 수 있게 남긴다.
SKIP_REASONS = {
    "google_drive": "GOOGLE_DRIVE_CLIENT_ID/SECRET/REDIRECT_URI 미설정",
    "github": "GITHUB_APP_ID/GITHUB_APP_SLUG/GITHUB_APP_PRIVATE_KEY 미설정",
    "google_drive:bindings": "Firestore 미설정 — Drive 조회 포트를 만들 수 없음",
    "github:bindings": "Firestore 미설정 — GitHub 조회 포트를 만들 수 없음",
    "github:private_key": "GITHUB_APP_PRIVATE_KEY 미설정 — App 인증 불가",
    "google_drive:webhook": "DRIVE_WATCH_CHANNEL_TOKEN 미설정",
    "github:webhook": "GITHUB_WEBHOOK_SECRET 미설정 — 서명 검증 불가",
}


def _mount_local(app: FastAPI, container: Container) -> None:
    ports = container.source_ports
    registration = container.source_registration
    authorize = container.facade.authorize_vws_action

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


def _mount_drive(
    app: FastAPI,
    container: Container,
    mounted: list[str],
    skipped: dict[str, str],
    *,
    spa: bool,
) -> None:
    source = container.settings.source
    if not source.drive_configured:
        skipped["google_drive"] = SKIP_REASONS["google_drive"]
        return

    ports = container.source_ports
    registration = container.source_registration
    authorize = container.facade.authorize_vws_action
    connections = ports.connections

    # 연결 시작은 조회 포트가 없어도 된다. 항상 붙인다.
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
            # provider 가 브라우저를 콜백으로 보낸다. Web UI 가 있으면
            # 원시 JSON 대신 Sources 화면으로 돌려보낸다. 번들이 없는
            # 배포에서는 돌려보낼 화면이 없으므로 JSON 을 유지한다.
            success_redirect=connected_redirect("google_drive") if spa else None,
        )
    )
    mounted.append("google_drive:oauth")

    bundle = container.drive
    if bundle is None:
        skipped["google_drive:bindings"] = SKIP_REASONS["google_drive:bindings"]
        return

    app.include_router(
        create_drive_mounts_router(
            picker_api_key=source.drive_picker_api_key,
            picker_app_id=source.drive_picker_app_id,
            provider_factory=bundle.provider_factory,
            credential_vault=ports.credential_vault,
            connection_credential_lookup=bundle.credential_lookup,
            tracking_scope_store=bundle.tracking_scope_store,
            mount_creation_callback=registration,
            # Picker 세션은 resource_id 가 connection_id, Mount 생성은
            # risk_workspace_id 다. 경로로 갈라 각자 맞는 스코프를 태운다.
            authz_dependency=authz.path_scoped(
                {
                    "/picker-session": authz.connection_scoped(
                        authorize, PublicVwsAction.SOURCE_MOUNT, connections
                    )
                },
                authz.workspace_scoped(authorize, PublicVwsAction.SOURCE_MOUNT),
            ),
        )
    )
    mounted.append("google_drive:mounts")

    if not source.drive_watch_channel_token:
        skipped["google_drive:webhook"] = SKIP_REASONS["google_drive:webhook"]
        return

    # webhook 은 provider 가 호출하므로 세션 authz 를 걸지 않는다.
    # 대신 channel token 으로 발신자를 검증한다.
    app.include_router(
        create_drive_webhook_router(
            adapter=bundle.adapter,
            channel_resolver=bundle.channel_resolver,
            channel_token=source.drive_watch_channel_token,
            change_sink=ports.change_sink,
        )
    )
    mounted.append("google_drive:webhook")


def _mount_github(
    app: FastAPI,
    container: Container,
    mounted: list[str],
    skipped: dict[str, str],
    *,
    spa: bool,
) -> None:
    source = container.settings.source
    if not source.github_configured:
        skipped["github"] = SKIP_REASONS["github"]
        return

    ports = container.source_ports
    registration = container.source_registration
    authorize = container.facade.authorize_vws_action
    connections = ports.connections

    app.include_router(
        create_github_install_router(
            app_slug=source.github_app_slug or "",
            state_store=ports.oauth_state_store,
            connection_creation_callback=registration,
            authz_dependency=authz.workspace_scoped(
                authorize, PublicVwsAction.SOURCE_MOUNT
            ),
            # provider 가 브라우저를 콜백으로 보낸다. Web UI 가 있으면
            # 원시 JSON 대신 Sources 화면으로 돌려보낸다. 번들이 없는
            # 배포에서는 돌려보낼 화면이 없으므로 JSON 을 유지한다.
            success_redirect=connected_redirect("github") if spa else None,
        )
    )
    mounted.append("github:install")

    bundle = container.github
    if bundle is None:
        # 왜 못 만들었는지 정확히 구분해 알린다. 뭉뚱그리면 설정을 고칠 때
        # 엉뚱한 곳을 보게 된다.
        reason = (
            "github:private_key"
            if not source.github_app_private_key
            else "github:bindings"
        )
        skipped[reason] = SKIP_REASONS[reason]
        return

    app.include_router(
        create_github_mounts_router(
            provider_factory=bundle.provider_factory,
            connection_installation_lookup=bundle.installation_lookup,
            tracking_scope_store=bundle.tracking_scope_store,
            mount_creation_callback=registration,
            # 저장소 목록은 connection_id, Mount 생성은 risk_workspace_id 다.
            authz_dependency=authz.path_scoped(
                {
                    "/repositories": authz.connection_scoped(
                        authorize, PublicVwsAction.SOURCE_MOUNT, connections
                    )
                },
                authz.workspace_scoped(authorize, PublicVwsAction.SOURCE_MOUNT),
            ),
        )
    )
    mounted.append("github:mounts")

    if bundle.webhook_processor is None:
        skipped["github:webhook"] = SKIP_REASONS["github:webhook"]
        return

    app.include_router(
        create_github_webhook_router(
            webhook_processor=bundle.webhook_processor,
            mount_resolver=bundle.mount_resolver,
            change_sink=ports.change_sink,
        )
    )
    mounted.append("github:webhook")


def _mount_source_routers(
    app: FastAPI, container: Container, *, spa: bool
) -> dict[str, object]:
    """Source 라우터를 붙이고 무엇을 붙였는지 보고한다."""
    mounted: list[str] = ["local"]
    skipped: dict[str, str] = {}

    # Local 은 외부 자격증명이 필요 없다. 항상 붙는다.
    _mount_local(app, container)
    _mount_drive(app, container, mounted, skipped, spa=spa)
    _mount_github(app, container, mounted, skipped, spa=spa)

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

    # OAuth 콜백을 어디로 돌려보낼지 정하려면 Web UI 유무를 라우터 배선
    # 시점에 이미 알아야 한다. 그래서 번들 경로를 먼저 확인한다.
    dist_env = os.environ.get("FRONTEND_DIST_DIR")
    dist_dir = Path(dist_env) if dist_env else None
    spa_ready = bool(dist_dir and (dist_dir / "index.html").is_file())

    source_status = _mount_source_routers(app, resolved, spa=spa_ready)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, object]:
        """상태와 함께 '무엇이 실제로 연결되어 있는지'를 돌려준다.

        비밀값은 담지 않는다. 어떤 저장소를 쓰는지, 어떤 provider 라우터가
        붙었는지, 분석 경로가 살아 있는지만 알린다.
        """
        ports = resolved.source_ports
        return {
            "status": "ok",
            "control_backend": resolved.backend,
            "queue": resolved.queue_backend,
            "credential_vault": type(ports.credential_vault).__name__,
            "staging_store": type(ports.staging_store).__name__,
            "oauth_state_store": type(ports.oauth_state_store).__name__,
            "change_relay": type(ports.change_relay).__name__,
            "google_login": (
                "configured"
                if resolved.settings.control.google_login_configured
                else "unconfigured"
            ),
            "intelligence": (
                "enabled" if resolved.intelligence_enabled else "disabled"
            ),
            "web": "served" if app.state.frontend_served else "not-bundled",
            "sources": source_status,
        }

    # Control API 는 미들웨어까지 함께 설치하므로 라우터 중에서는 마지막이다.
    create_control_api_bundle(resolved.control_api).install(app)

    # Web UI 는 **모든 API 라우터 뒤에** 붙는다. Starlette 는 등록 순서대로
    # 매칭하므로 먼저 붙이면 catch-all 이 API 를 가린다.
    app.state.frontend_served = (
        install_frontend(app, dist_dir) if dist_dir else False
    )
    return app


__all__ = ["create_app"]
