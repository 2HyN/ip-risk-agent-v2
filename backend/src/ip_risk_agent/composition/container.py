"""Integration 전용 조립 컨테이너.

세 Plane 은 전부 "필요한 것을 생성자로 주입받는다"는 원칙으로 만들어졌다.
그 실물을 만들어 하나로 묶는 곳이 여기다 (Master Spec 61).

GCP 자원이 없어도 앱이 뜬다. 저장소·큐·자격증명 보관소는 설정이 없으면
in-memory 로 내려간다. in-memory 는 프로세스 상태이므로 개발과 통합 검증
전용이며, 재시작하면 데이터가 사라진다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from ip_risk_agent.api import (
    ApplicationHardeningConfig,
    ApplicationSessionConfig,
    ControlApiDependencies,
)
from ip_risk_agent.api.auth import (
    AuthRouterDependencies,
    GoogleOidcClient,
    GoogleOidcConfig,
)
from ip_risk_agent.api.common import CursorCodec, OidcProviderUnavailableError
from ip_risk_agent.api.history import HistoryRouterDependencies
from ip_risk_agent.api.notifications import NotificationRouterDependencies
from ip_risk_agent.api.risks import RiskRouterDependencies
from ip_risk_agent.api.security import SecurityRouterDependencies
from ip_risk_agent.api.workspaces import WorkspaceRouterDependencies
from ip_risk_agent.application.auth import AuthenticationService, GoogleOidcIdentity
from ip_risk_agent.application.history import HistoryQueryService
from ip_risk_agent.application.notifications import NotificationService
from ip_risk_agent.application.observability import StructuredLogger
from ip_risk_agent.application.process_change import InMemoryTaskEnqueuer
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
)
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.application.risk_review import RiskReviewService
from ip_risk_agent.application.security_policy import WorkspaceSecurityService
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.connectors.common.credential_vault import InMemoryCredentialVault
from ip_risk_agent.connectors.common.oauth_state import InMemoryOAuthStateStore
from ip_risk_agent.connectors.local.staging_store import InMemoryLocalStagingStore

from .gcp.relay import ChangeRelayStore, InMemoryChangeRelayStore
from .providers import (
    DriveProviderBundle,
    GitHubProviderBundle,
    build_drive_bundle,
    build_github_bundle,
)

from .runtime import id_factory, utc_clock
from .sinks import ControlSourceChangeSink
from .settings import Settings
from .source_callbacks import (
    ConnectionRegistry,
    DeviceRegistry,
    SourceRegistrationService,
)

_PLACEHOLDER_OIDC = GoogleOidcConfig(
    client_id="unconfigured",
    client_secret="unconfigured",
    redirect_uri="http://127.0.0.1:8000/api/v1/auth/google/callback",
    post_login_uri="http://127.0.0.1:8000",
)


class UnavailableOidcClient:
    """Google 자격증명이 없을 때 쓰는 클라이언트.

    로그인 자체를 막되, 라우트는 존재하게 두어 앱 형태가 배포와 같도록 한다.
    개발용 우회 로그인은 두지 않는다 — 인증 우회는 어떤 조건에서도 만들지 않는다.
    """

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        raise OidcProviderUnavailableError(
            "Google login is not configured on this deployment"
        )

    async def fetch_identity(self, request: Request) -> GoogleOidcIdentity:
        raise OidcProviderUnavailableError(
            "Google login is not configured on this deployment"
        )


@dataclass(frozen=True, slots=True)
class SourcePorts:
    """Source Plane 이 요구하는 포트의 현재 구현.

    GCP 를 붙일 때 이 필드만 실물로 교체하면 된다. 교체 지점을 한곳에 모아
    "무엇이 아직 in-memory 인가"를 코드로 알 수 있게 했다.
    """

    change_sink: Any
    credential_vault: Any
    oauth_state_store: Any
    staging_store: Any
    change_relay: ChangeRelayStore
    connections: ConnectionRegistry
    devices: DeviceRegistry


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    observer: StructuredLogger
    unit_of_work_factory: Any
    task_enqueuer: Any
    facade: ControlPlaneFacade
    control_api: ControlApiDependencies
    source_ports: SourcePorts
    source_registration: SourceRegistrationService
    intelligence: Any | None = field(default=None)
    drive: DriveProviderBundle | None = field(default=None)
    github: GitHubProviderBundle | None = field(default=None)
    bindings: Any | None = field(default=None)

    @property
    def backend(self) -> str:
        return self.settings.control.backend

    @property
    def intelligence_enabled(self) -> bool:
        return self.intelligence is not None

    @property
    def queue_backend(self) -> str:
        """어떤 큐가 실제로 붙었는지. in-memory 면 워커가 작업을 못 받는다."""
        return "cloud-tasks" if self.settings.queue.configured else "in-memory"


def _build_unit_of_work_factory(settings: Settings) -> Any:
    """Firestore 설정이 있으면 그것을, 없으면 in-memory 를 쓴다."""
    control = settings.control
    if control.backend == "firestore":
        # 실제 GCP 연동 지점. 자격증명이 없는 환경에서는 import 자체가 실패할 수
        # 있으므로 필요한 순간에만 불러온다.
        from google.cloud.firestore_v1 import AsyncClient  # noqa: PLC0415

        from ip_risk_agent.persistence.core_firestore import (  # noqa: PLC0415
            FirestoreControlUnitOfWorkFactory,
        )

        client = AsyncClient(
            project=control.gcp_project_id, database=control.firestore_database
        )
        return FirestoreControlUnitOfWorkFactory.from_client(client, max_attempts=5)
    return InMemoryControlStore()


def _build_oidc(settings: Settings) -> tuple[GoogleOidcClient, GoogleOidcConfig]:
    control = settings.control
    if not control.google_login_configured:
        return UnavailableOidcClient(), _PLACEHOLDER_OIDC

    from ip_risk_agent.api.auth import AuthlibGoogleOidcClient  # noqa: PLC0415

    config = GoogleOidcConfig(
        client_id=control.google_login_client_id or "",
        client_secret=control.google_login_client_secret or "",
        redirect_uri=control.google_login_redirect_uri or "",
        post_login_uri=control.app_public_base_url,
    )
    return AuthlibGoogleOidcClient(config), config


def _build_intelligence(settings: Settings) -> Any | None:
    """Analyzer registry. 모델 식별자가 없으면 만들지 않는다."""
    intelligence = settings.intelligence
    if not intelligence.enabled:
        return None

    from ip_risk_agent.intelligence.public import (  # noqa: PLC0415
        create_facade_from_env,
    )

    env = intelligence.as_env()
    retriever = None
    if intelligence.rag_configured:
        from ip_risk_agent.intelligence.rag.engine import (  # noqa: PLC0415
            RagEngineConfig,
            RagEngineRetriever,
        )

        retriever = RagEngineRetriever(RagEngineConfig.from_env(env))
    return create_facade_from_env(env, retriever=retriever)


def _build_credential_vault(settings: Settings) -> Any:
    """Secret Manager 가 가능하면 그것을, 아니면 in-memory 를 쓴다."""
    project_id = settings.control.gcp_project_id
    if settings.control.backend == "firestore" and project_id:
        from .gcp.secrets import SecretManagerCredentialVault  # noqa: PLC0415

        return SecretManagerCredentialVault(project_id)
    return InMemoryCredentialVault()


def _build_oauth_state_store(settings: Settings) -> Any:
    """다중 인스턴스에서는 공유 저장소가 필수다."""
    control = settings.control
    if control.backend == "firestore" and control.gcp_project_id:
        from .gcp.state import FirestoreOAuthStateStore  # noqa: PLC0415

        return FirestoreOAuthStateStore(
            project_id=control.gcp_project_id,
            database=control.firestore_database or "(default)",
        )
    return InMemoryOAuthStateStore()


def _build_staging_store(settings: Settings) -> Any:
    bucket = settings.source.local_staging_bucket
    if bucket:
        from .gcp.storage import GcsLocalStagingStore  # noqa: PLC0415

        return GcsLocalStagingStore(bucket)
    return InMemoryLocalStagingStore()


def _build_bindings(settings: Settings) -> Any | None:
    """provider 식별자 매핑 저장소. Firestore 가 없으면 만들지 않는다.

    없으면 Drive/GitHub 의 mounts·webhook 라우터를 붙이지 않는다. 반쯤 조립해
    런타임에 실패하게 두지 않는다.
    """
    control = settings.control
    if control.backend == "firestore" and control.gcp_project_id:
        from .gcp.stores import FirestoreMountBindingStore  # noqa: PLC0415

        return FirestoreMountBindingStore(
            project_id=control.gcp_project_id,
            database=control.firestore_database or "(default)",
        )
    return None


def _build_change_relay(settings: Settings) -> ChangeRelayStore:
    control = settings.control
    if control.backend == "firestore" and control.gcp_project_id:
        from .gcp.relay import FirestoreChangeRelayStore  # noqa: PLC0415

        return FirestoreChangeRelayStore(
            project_id=control.gcp_project_id,
            database=control.firestore_database or "(default)",
        )
    return InMemoryChangeRelayStore()


def _build_task_enqueuer(settings: Settings) -> Any:
    """큐 설정이 없으면 in-memory 로 하강한다.

    워커를 별도 프로세스로 띄우는 배포에서 in-memory 로 남으면 변경이
    큐에 들어가도 아무도 가져가지 않는다. `/health` 가 이 상태를 드러낸다.
    """
    queue = settings.queue
    if queue.configured:
        from .gcp.queue import CloudTasksEnqueuer  # noqa: PLC0415

        return CloudTasksEnqueuer(
            project_id=queue.project_id or "",
            location=queue.location or "",
            queue=queue.queue or "",
            worker_url=queue.worker_url or "",
            service_account_email=queue.service_account_email or "",
        )
    return InMemoryTaskEnqueuer()


def build_container(
    env: Mapping[str, str],
    *,
    oidc_client: GoogleOidcClient | None = None,
    unit_of_work_factory: Any | None = None,
    task_enqueuer: Any | None = None,
) -> Container:
    """전체 의존성 그래프를 한 번에 만든다.

    테스트는 `oidc_client` 등을 주입해 외부 자원 없이 전 경로를 돌린다.
    Agent 1 이 자신의 API 테스트에서 쓰는 방식과 같다.
    """
    settings = Settings.from_env(env)
    control = settings.control
    observer = StructuredLogger()

    uow = unit_of_work_factory or _build_unit_of_work_factory(settings)
    queue = task_enqueuer or _build_task_enqueuer(settings)

    facade = ControlPlaneFacade(
        unit_of_work_factory=uow,
        task_enqueuer=queue,
        clock=utc_clock,
        id_factory=id_factory,
        config=ControlPlaneFacadeConfig(),
        observer=observer,
    )

    authentication = AuthenticationService(
        unit_of_work_factory=uow, clock=utc_clock, concurrency_attempts=3
    )
    administration = WorkspaceAdministrationService(
        unit_of_work_factory=uow, clock=utc_clock, id_factory=id_factory
    )
    review = RiskReviewService(unit_of_work_factory=uow, clock=utc_clock)
    history = HistoryQueryService(unit_of_work_factory=uow, clock=utc_clock)
    notifications = NotificationService(unit_of_work_factory=uow, clock=utc_clock)
    security = WorkspaceSecurityService(
        unit_of_work_factory=uow, clock=utc_clock, id_factory=id_factory
    )
    cursor_codec = CursorCodec(control.session_secret)

    built_client, oidc_config = _build_oidc(settings)
    oidc = oidc_client or built_client

    control_api = ControlApiDependencies(
        auth=AuthRouterDependencies(oidc, oidc_config, authentication),
        workspaces=WorkspaceRouterDependencies(
            uow, administration, authentication, cursor_codec
        ),
        risks=RiskRouterDependencies(
            uow, review, history, authentication, cursor_codec
        ),
        history=HistoryRouterDependencies(history, authentication, cursor_codec),
        security=SecurityRouterDependencies(security, authentication),
        notifications=NotificationRouterDependencies(
            notifications, authentication, cursor_codec
        ),
        session=ApplicationSessionConfig(
            secret_key=control.session_secret,
            https_only=control.https_only,
        ),
        hardening=ApplicationHardeningConfig(
            trusted_hosts=control.trusted_hosts,
            allowed_origins=control.allowed_origins,
        ),
        observer=observer,
    )

    connections = ConnectionRegistry()
    devices = DeviceRegistry()
    change_relay = _build_change_relay(settings)
    source_ports = SourcePorts(
        change_sink=ControlSourceChangeSink(facade, relay=change_relay),
        credential_vault=_build_credential_vault(settings),
        oauth_state_store=_build_oauth_state_store(settings),
        staging_store=_build_staging_store(settings),
        change_relay=change_relay,
        connections=connections,
        devices=devices,
    )
    source_registration = SourceRegistrationService(
        facade.register_source_metadata,
        connections=connections,
        devices=devices,
    )

    bindings = _build_bindings(settings)
    drive = build_drive_bundle(
        settings,
        credential_vault=source_ports.credential_vault,
        bindings=bindings,
    )
    github = build_github_bundle(settings, bindings=bindings)

    return Container(
        settings=settings,
        observer=observer,
        unit_of_work_factory=uow,
        task_enqueuer=queue,
        facade=facade,
        control_api=control_api,
        source_ports=source_ports,
        source_registration=source_registration,
        intelligence=_build_intelligence(settings),
        drive=drive,
        github=github,
        bindings=bindings,
    )


__all__ = ["Container", "SourcePorts", "UnavailableOidcClient", "build_container"]
