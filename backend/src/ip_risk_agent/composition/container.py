"""Integration-owned dependency graph for API and worker processes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from iprisk_contracts import SourceType

from ip_risk_agent.api import (
    ApplicationHardeningConfig,
    ApplicationSessionConfig,
    ControlApiBundle,
    ControlApiDependencies,
    create_control_api_bundle,
)
from ip_risk_agent.api.auth import (
    AuthRouterDependencies,
    AuthlibGoogleOidcClient,
    GoogleOidcConfig,
)
from ip_risk_agent.api.common import CursorCodec, CurrentPrincipalDependency
from ip_risk_agent.api.history import HistoryRouterDependencies
from ip_risk_agent.api.notifications import NotificationRouterDependencies
from ip_risk_agent.api.risks import RiskRouterDependencies
from ip_risk_agent.api.security import SecurityRouterDependencies
from ip_risk_agent.api.workspaces import WorkspaceRouterDependencies
from ip_risk_agent.application.auth import (
    AuthenticatedSession,
    AuthenticationError,
    AuthenticationService,
)
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

from .health import HealthRegistry, ReadinessCheck
from .device_auth import (
    DesktopDeviceAuthService,
    InMemoryDeviceAuthStore,
    create_device_enrollment_router,
)
from .analyzer_completeness import CompleteIntelligenceFacade
from .originals import OriginalSourceService, create_original_source_router
from .pipeline import AnalysisPipeline
from .providers import SourceAdapterRegistry, SourceRouterBundle
from .runtime import opaque_id, utc_now
from .settings import AppRole, RuntimeProfile, Settings, SettingsError
from .task_auth import (
    DenyTaskAuthenticator,
    StaticBearerTaskAuthenticator,
    TaskAuthenticator,
)


@dataclass(slots=True)
class ContainerOverrides:
    unit_of_work_factory: Any | None = None
    task_enqueuer: Any | None = None
    oidc_client: Any | None = None
    source_adapters: tuple[Any, ...] = ()
    source_routers: SourceRouterBundle = field(default_factory=SourceRouterBundle)
    extra_api_routers: tuple[Any, ...] = ()
    intelligence: Any | None = None
    task_authenticator: TaskAuthenticator | None = None
    observer: StructuredLogger | None = None
    close_callbacks: tuple[Any, ...] = ()
    device_auth_service: DesktopDeviceAuthService | None = None


@dataclass(slots=True)
class RuntimeContainer:
    settings: Settings
    unit_of_work_factory: Any
    task_enqueuer: Any
    authentication: AuthenticationService
    control_facade: ControlPlaneFacade
    adapters: SourceAdapterRegistry
    control_api: ControlApiBundle | None
    source_routers: SourceRouterBundle
    extra_api_routers: tuple[Any, ...]
    original_router: Any | None
    pipeline: AnalysisPipeline | None
    task_authenticator: TaskAuthenticator
    health: HealthRegistry
    device_auth_service: DesktopDeviceAuthService | None = None
    close_callbacks: tuple[Any, ...] = ()

    async def close(self) -> None:
        for callback in reversed(self.close_callbacks):
            result = callback()
            if hasattr(result, "__await__"):
                await result


def build_container(
    settings: Settings,
    *,
    overrides: ContainerOverrides | None = None,
) -> RuntimeContainer:
    overrides = overrides or ContainerOverrides()
    settings.validate()
    if settings.profile is RuntimeProfile.PRODUCTION and (
        overrides.unit_of_work_factory is None or overrides.task_enqueuer is None
    ):
        raise SettingsError(
            "production container requires explicit Firestore and Cloud Tasks adapters"
        )
    store = overrides.unit_of_work_factory or InMemoryControlStore()
    queue = overrides.task_enqueuer or InMemoryTaskEnqueuer()
    if settings.profile is RuntimeProfile.PRODUCTION and (
        isinstance(store, InMemoryControlStore)
        or isinstance(queue, InMemoryTaskEnqueuer)
    ):
        raise SettingsError("production container cannot use in-memory adapters")
    observer = overrides.observer or StructuredLogger()
    authentication = AuthenticationService(unit_of_work_factory=store, clock=utc_now)

    async def session_is_current(user_id: str, session_version: int) -> bool:
        try:
            await authentication.resolve_session(
                AuthenticatedSession(user_id, session_version)
            )
        except AuthenticationError:
            return False
        return True

    device_auth_service = overrides.device_auth_service
    if settings.role is AppRole.API and device_auth_service is None:
        if settings.profile is RuntimeProfile.PRODUCTION:
            raise SettingsError(
                "production API requires a durable desktop device auth service"
            )
        device_auth_service = DesktopDeviceAuthService(
            store=InMemoryDeviceAuthStore(),
            session_version_validator=session_is_current,
            clock=utc_now,
        )
    facade = ControlPlaneFacade(
        unit_of_work_factory=store,
        task_enqueuer=queue,
        clock=utc_now,
        id_factory=opaque_id,
        config=ControlPlaneFacadeConfig(
            requested_analysis_types=settings.requested_analysis_types
        ),
        observer=observer,
    )
    adapters = SourceAdapterRegistry(overrides.source_adapters)
    task_authenticator = overrides.task_authenticator or DenyTaskAuthenticator()

    intelligence = overrides.intelligence
    if intelligence is not None and not isinstance(
        intelligence, CompleteIntelligenceFacade
    ):
        active_types = getattr(intelligence, "active_analysis_types", None)
        if active_types is not None:
            intelligence = CompleteIntelligenceFacade(
                intelligence,
                configured_analysis_types=settings.requested_analysis_types,
                active_analysis_types=tuple(active_types),
            )
    pipeline = None
    if intelligence is not None:
        pipeline = AnalysisPipeline(
            control_facade=facade,
            adapters=adapters,
            intelligence=intelligence,
        )

    control_api = None
    original_router = None
    if settings.role is AppRole.API:
        oidc_config, oidc_client = _oidc(settings, overrides.oidc_client)
        current = CurrentPrincipalDependency(authentication)
        control_api = _control_api(
            settings=settings,
            store=store,
            authentication=authentication,
            facade=facade,
            observer=observer,
            oidc_config=oidc_config,
            oidc_client=oidc_client,
        )
        original_router = create_original_source_router(
            service=OriginalSourceService(control_facade=facade, adapters=adapters),
            principal_resolver=current,
        )
        assert device_auth_service is not None
        extra_api_routers = (
            create_device_enrollment_router(
                devices=device_auth_service,
                principal_resolver=current,
            ),
            *overrides.extra_api_routers,
        )
    else:
        extra_api_routers = overrides.extra_api_routers

    checks = [
        ReadinessCheck(
            "canonical_store",
            True,
            "in_memory" if isinstance(store, InMemoryControlStore) else "configured",
        ),
        ReadinessCheck(
            "task_queue",
            True,
            "in_memory" if isinstance(queue, InMemoryTaskEnqueuer) else "configured",
        ),
    ]
    if settings.role is AppRole.WORKER:
        checks.extend(
            (
                ReadinessCheck(
                    "analysis_pipeline",
                    pipeline is not None,
                    "configured" if pipeline is not None else "missing",
                ),
                ReadinessCheck(
                    "source_adapters",
                    bool(adapters.source_types),
                    ",".join(item.value for item in adapters.source_types) or "missing",
                ),
                ReadinessCheck(
                    "task_identity",
                    not isinstance(task_authenticator, DenyTaskAuthenticator),
                    (
                        "configured"
                        if not isinstance(task_authenticator, DenyTaskAuthenticator)
                        else "missing"
                    ),
                ),
            )
        )
        if settings.profile is RuntimeProfile.PRODUCTION:
            if (
                pipeline is None
                or not isinstance(intelligence, CompleteIntelligenceFacade)
                or set(adapters.source_types) != set(SourceType)
                or isinstance(
                    task_authenticator,
                    (DenyTaskAuthenticator, StaticBearerTaskAuthenticator),
                )
            ):
                raise SettingsError(
                    "production worker requires complete intelligence, all source adapters, "
                    "and non-static task identity"
                )
    elif settings.profile is RuntimeProfile.PRODUCTION and (
        not overrides.source_routers.web
        or not overrides.source_routers.webhooks
        or not overrides.source_routers.desktop
        or set(adapters.source_types) != set(SourceType)
    ):
        raise SettingsError(
            "production API requires all source adapters and web, webhook, and desktop routers"
        )
    return RuntimeContainer(
        settings=settings,
        unit_of_work_factory=store,
        task_enqueuer=queue,
        authentication=authentication,
        control_facade=facade,
        adapters=adapters,
        control_api=control_api,
        source_routers=overrides.source_routers,
        extra_api_routers=extra_api_routers,
        original_router=original_router,
        pipeline=pipeline,
        task_authenticator=task_authenticator,
        health=HealthRegistry(tuple(checks)),
        device_auth_service=device_auth_service,
        close_callbacks=overrides.close_callbacks,
    )


def _control_api(
    *,
    settings: Settings,
    store,
    authentication,
    facade,
    observer,
    oidc_config,
    oidc_client,
) -> ControlApiBundle:
    administration = WorkspaceAdministrationService(
        unit_of_work_factory=store,
        clock=utc_now,
        id_factory=opaque_id,
    )
    review = RiskReviewService(unit_of_work_factory=store, clock=utc_now)
    history = HistoryQueryService(unit_of_work_factory=store, clock=utc_now)
    notifications = NotificationService(unit_of_work_factory=store, clock=utc_now)
    security = WorkspaceSecurityService(
        unit_of_work_factory=store,
        clock=utc_now,
        id_factory=opaque_id,
    )
    cursor = CursorCodec(settings.session_secret)
    parsed_host = settings.public_base_url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    dependencies = ControlApiDependencies(
        auth=AuthRouterDependencies(oidc_client, oidc_config, authentication),
        workspaces=WorkspaceRouterDependencies(
            store,
            administration,
            authentication,
            cursor,
        ),
        risks=RiskRouterDependencies(store, review, history, authentication, cursor),
        history=HistoryRouterDependencies(history, authentication, cursor),
        security=SecurityRouterDependencies(security, authentication),
        notifications=NotificationRouterDependencies(
            notifications,
            authentication,
            cursor,
        ),
        session=ApplicationSessionConfig(
            secret_key=settings.session_secret,
            https_only=settings.profile is RuntimeProfile.PRODUCTION,
        ),
        hardening=ApplicationHardeningConfig(
            trusted_hosts=tuple(
                dict.fromkeys((parsed_host, "testserver", "localhost", "127.0.0.1"))
            )
        ),
        observer=observer,
    )
    return create_control_api_bundle(dependencies)


def _oidc(settings: Settings, override):
    redirect = settings.google_login_redirect_uri or (
        settings.public_base_url.rstrip("/") + "/api/v1/auth/google/callback"
    )
    config = GoogleOidcConfig(
        client_id=settings.google_login_client_id or "local-disabled-client",
        client_secret=settings.google_login_client_secret or "local-disabled-secret",
        redirect_uri=redirect,
        post_login_uri=settings.public_base_url.rstrip("/") + "/app",
    )
    if override is not None:
        return config, override
    if settings.google_login_client_id is not None:
        return config, AuthlibGoogleOidcClient(config)
    return config, _UnavailableOidcClient()


class _UnavailableOidcClient:
    async def authorize_redirect(self, request: Request, redirect_uri: str):
        raise RuntimeError("Google login is not configured")

    async def fetch_identity(self, request: Request):
        raise RuntimeError("Google login is not configured")


__all__ = [
    "ContainerOverrides",
    "RuntimeContainer",
    "build_container",
]
