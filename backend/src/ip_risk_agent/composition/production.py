"""Production-only composition over the durable Google Cloud foundation.

The module is imported by the two process entrypoints only for ``APP_ENV=production``.
It does not create clients at import time and keeps API/Worker capabilities separate.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from iprisk_contracts import SourceType

from ip_risk_agent.api.common import CurrentPrincipalDependency
from ip_risk_agent.application.public_facade import SourceMetadataRegistrationCommand
from ip_risk_agent.connectors.common.errors import NotFoundError
from ip_risk_agent.connectors.common.oauth_state import OAuthStateStore
from ip_risk_agent.connectors.common.runtime_store import (
    DriveRuntime,
    GitHubRuntime,
    LocalConnectionStatus,
    LocalRuntime,
)
from ip_risk_agent.connectors.github.adapter import GitHubAdapter
from ip_risk_agent.connectors.github.client import GitHubAppProviderFactory
from ip_risk_agent.connectors.github.install_routes import create_github_install_router
from ip_risk_agent.connectors.github.mounts_routes import create_github_mounts_router
from ip_risk_agent.connectors.github.routes import create_github_webhook_router
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope
from ip_risk_agent.connectors.github.webhook_processor import GitHubWebhookProcessor
from ip_risk_agent.connectors.google_drive.adapter import GoogleDriveAdapter
from ip_risk_agent.connectors.google_drive.client import GoogleDriveProviderFactory
from ip_risk_agent.connectors.google_drive.mounts_routes import create_drive_mounts_router
from ip_risk_agent.connectors.google_drive.oauth import HttpxDriveOAuthClient
from ip_risk_agent.connectors.google_drive.oauth_routes import create_drive_oauth_router
from ip_risk_agent.connectors.google_drive.routes import create_drive_webhook_router
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope
from ip_risk_agent.connectors.local.adapter import LocalAdapter
from ip_risk_agent.connectors.local.device_lookup import LocalDeviceContext
from ip_risk_agent.connectors.local.routes import (
    MountRegistrationResponse,
    create_local_desktop_router,
)
from ip_risk_agent.core.common import stable_key
from ip_risk_agent.gcp.identity import GoogleOidcTaskAuthenticator
from ip_risk_agent.gcp.operational_firestore import (
    FirestoreMaintenanceStore,
    FirestoreOAuthStateStore,
    FirestorePendingConnectionStore,
    FirestoreRuntimeStore,
)
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.license.package_metadata import HttpPackageMetadataProvider
from ip_risk_agent.intelligence.patent.kipris import KiprisClient
from ip_risk_agent.intelligence.public import IntelligenceFacade, create_analyzer_registry
from ip_risk_agent.intelligence.rag.engine import RagEngineConfig, RagEngineRetriever
from ip_risk_agent.gcp_contract import TASKS_SERVICE_ACCOUNT

from .container import RuntimeComposition, RuntimeCompositionContext
from .device_auth import DeviceSourceAuthorizer, DeviceWorkspaceAuthorizer
from .providers import SourceRouterBundle
from .runtime import utc_now
from .scheduler_operations import ProductionSchedulerOperations
from .scheduler_routes import create_scheduler_router
from .settings import AppRole, Settings, SettingsError
from .sinks import ControlSourceChangeSink
from .source_auth import SessionSourceAuthorizer, SourceResourceScope
from .source_bindings import DriveMountConnectionLookup, GitHubMountConnectionLookup
from .source_completion import ProductSourceCompletionRedirect
from .source_registration import SourceRegistrationService


def build_google_cloud_runtime_composer(foundation):
    """Return a role-aware callback consumed by :func:`build_container`."""

    if foundation.clients.runtime_secrets is None:
        raise SettingsError("Secret Manager runtime secret reader is unavailable")
    return _GoogleCloudRuntimeComposer(foundation)


class _GoogleCloudRuntimeComposer:
    def __init__(self, foundation) -> None:
        self._foundation = foundation

    def __call__(self, context: RuntimeCompositionContext) -> RuntimeComposition:
        if context.settings.role is AppRole.API:
            return _compose_api(self._foundation, context)
        if context.settings.role is AppRole.WORKER:
            return _compose_worker(self._foundation, context)
        raise SettingsError("Google Cloud runtime composition supports API and Worker only")


@dataclass(slots=True)
class _SourceRuntime:
    pending: FirestorePendingConnectionStore
    drive_runtime: FirestoreRuntimeStore[DriveRuntime]
    drive_tracking: FirestoreRuntimeStore[DriveTrackingScope]
    github_runtime: FirestoreRuntimeStore[GitHubRuntime]
    github_tracking: FirestoreRuntimeStore[GitHubTrackingScope]
    local_runtime: FirestoreRuntimeStore[LocalRuntime]
    drive_adapter: GoogleDriveAdapter
    github_adapter: GitHubAdapter
    local_adapter: LocalAdapter
    drive_provider_factory: GoogleDriveProviderFactory
    github_provider_factory: GitHubAppProviderFactory


def _source_runtime(foundation, settings: Settings) -> _SourceRuntime:
    assert settings.drive_client_id is not None
    assert settings.drive_client_secret is not None
    assert settings.github_app_id is not None
    assert settings.github_private_key_secret_id is not None
    backend = foundation.operational_backend
    pending = FirestorePendingConnectionStore(backend)
    drive_runtime = FirestoreRuntimeStore(
        backend,
        collection="source_operational_drive_runtime",
        model=DriveRuntime,
    )
    drive_tracking = FirestoreRuntimeStore(
        backend,
        collection="source_operational_drive_tracking",
        model=DriveTrackingScope,
    )
    github_runtime = FirestoreRuntimeStore(
        backend,
        collection="source_operational_github_runtime",
        model=GitHubRuntime,
    )
    github_tracking = FirestoreRuntimeStore(
        backend,
        collection="source_operational_github_tracking",
        model=GitHubTrackingScope,
    )
    local_runtime = FirestoreRuntimeStore(
        backend,
        collection="source_operational_local_runtime",
        model=LocalRuntime,
    )
    drive_factory = GoogleDriveProviderFactory(
        settings.drive_client_id,
        settings.drive_client_secret,
    )
    github_factory = GitHubAppProviderFactory(
        app_id=settings.github_app_id,
        private_key_pem=_secret(foundation, settings.github_private_key_secret_id),
    )
    drive_adapter = GoogleDriveAdapter(
        provider_factory=drive_factory,
        credential_vault=foundation.credential_vault,
        connection_lookup=DriveMountConnectionLookup(pending),
        tracking_scope_store=drive_tracking,
        runtime_store=drive_runtime,
    )
    github_adapter = GitHubAdapter(
        provider_factory=github_factory,
        connection_lookup=GitHubMountConnectionLookup(pending),
        tracking_scope_store=github_tracking,
    )
    local_adapter = LocalAdapter(
        staging_store=foundation.staging_store,
        device_lookup=_LocalDeviceLookup(foundation.device_auth_store),
        runtime_store=local_runtime,
    )
    return _SourceRuntime(
        pending=pending,
        drive_runtime=drive_runtime,
        drive_tracking=drive_tracking,
        github_runtime=github_runtime,
        github_tracking=github_tracking,
        local_runtime=local_runtime,
        drive_adapter=drive_adapter,
        github_adapter=github_adapter,
        local_adapter=local_adapter,
        drive_provider_factory=drive_factory,
        github_provider_factory=github_factory,
    )


def _compose_api(foundation, context: RuntimeCompositionContext) -> RuntimeComposition:
    settings = context.settings
    assert context.device_auth_service is not None
    assert settings.drive_client_id is not None
    assert settings.drive_client_secret is not None
    assert settings.drive_redirect_uri is not None
    assert settings.drive_watch_channel_token is not None
    assert settings.drive_webhook_base_url is not None
    assert settings.scheduler_service_account is not None
    assert settings.github_app_slug is not None
    assert settings.github_webhook_secret_id is not None

    source = _source_runtime(foundation, settings)
    principal = CurrentPrincipalDependency(context.authentication)
    registration = SourceRegistrationService(
        store=source.pending,
        control_facade=context.control_facade,
        principal_resolver=principal,
        clock=utc_now,
    )
    workspace_auth = SessionSourceAuthorizer(
        principal_resolver=principal,
        control_facade=context.control_facade,
        scope=SourceResourceScope.WORKSPACE,
    )
    connection_auth = SessionSourceAuthorizer(
        principal_resolver=principal,
        control_facade=context.control_facade,
        scope=SourceResourceScope.CONNECTION,
        connection_resolver=registration,
    )
    mount_auth = SessionSourceAuthorizer(
        principal_resolver=principal,
        control_facade=context.control_facade,
        scope=SourceResourceScope.MOUNT,
    )
    completion = ProductSourceCompletionRedirect(settings.public_base_url)
    oauth_state: OAuthStateStore = FirestoreOAuthStateStore(
        foundation.operational_backend
    )
    sink = ControlSourceChangeSink(context.control_facade)
    scheduler = create_scheduler_router(
        authenticator=GoogleOidcTaskAuthenticator(
            audience=settings.public_base_url,
            service_account_email=settings.scheduler_service_account,
        ),
        operations=ProductionSchedulerOperations(
            maintenance_store=FirestoreMaintenanceStore(
                foundation.operational_backend
            ),
            drive_tracking_store=source.drive_tracking,
            github_tracking_store=source.github_tracking,
            local_runtime_store=source.local_runtime,
            drive_adapter=source.drive_adapter,
            github_adapter=source.github_adapter,
            local_adapter=source.local_adapter,
            control_facade=context.control_facade,
            change_sink=sink,
            drive_webhook_url=settings.drive_webhook_base_url,
            drive_channel_token=settings.drive_watch_channel_token,
            clock=utc_now,
        ),
    )

    drive_oauth = create_drive_oauth_router(
        client_id=settings.drive_client_id,
        redirect_uri=settings.drive_redirect_uri,
        state_store=oauth_state,
        oauth_client=HttpxDriveOAuthClient(
            client_id=settings.drive_client_id,
            client_secret=settings.drive_client_secret,
            redirect_uri=settings.drive_redirect_uri,
        ),
        credential_vault=foundation.credential_vault,
        connection_creation_callback=registration,
        authz_dependency=workspace_auth,
        completion_redirect=completion,
    )
    drive_mounts = create_drive_mounts_router(
        provider_factory=source.drive_provider_factory,
        credential_vault=foundation.credential_vault,
        connection_credential_lookup=registration,
        tracking_scope_store=source.drive_tracking,
        mount_creation_callback=registration,
        connection_authz_dependency=connection_auth,
        workspace_authz_dependency=workspace_auth,
    )
    drive_webhook = create_drive_webhook_router(
        adapter=source.drive_adapter,
        channel_resolver=_DriveChannelResolver(
            source.drive_runtime,
            source.pending,
            context.control_facade,
        ),
        channel_token=settings.drive_watch_channel_token,
        change_sink=sink,
    )
    github_install = create_github_install_router(
        app_slug=settings.github_app_slug,
        state_store=oauth_state,
        connection_creation_callback=registration,
        authz_dependency=workspace_auth,
        completion_redirect=completion,
    )
    github_mounts = create_github_mounts_router(
        provider_factory=source.github_provider_factory,
        connection_installation_lookup=registration,
        tracking_scope_store=source.github_tracking,
        mount_creation_callback=registration,
        connection_authz_dependency=connection_auth,
        workspace_authz_dependency=workspace_auth,
    )
    github_webhook = create_github_webhook_router(
        webhook_processor=GitHubWebhookProcessor(
            provider_factory=source.github_provider_factory,
            connection_lookup=GitHubMountConnectionLookup(source.pending),
            tracking_scope_store=source.github_tracking,
            runtime_store=source.github_runtime,
            webhook_secret=_secret(foundation, settings.github_webhook_secret_id),
        ),
        mount_resolver=_GitHubMountResolver(
            source.github_tracking,
            context.control_facade,
        ),
        change_sink=sink,
    )
    local_callbacks = _LocalRegistrationCallbacks(
        devices=context.device_auth_service,
        control_facade=context.control_facade,
        runtime_store=source.local_runtime,
    )
    local_desktop = create_local_desktop_router(
        staging_store=foundation.staging_store,
        change_sink=sink,
        device_registration_callback=local_callbacks,
        mount_creation_callback=local_callbacks,
        device_registration_authz_dependency=local_callbacks.authorize_device,
        workspace_authz_dependency=DeviceWorkspaceAuthorizer(
            devices=context.device_auth_service,
            control_facade=context.control_facade,
        ),
        mount_authz_dependency=DeviceSourceAuthorizer(
            devices=context.device_auth_service,
            control_facade=context.control_facade,
        ),
    )
    return RuntimeComposition(
        source_adapters=(
            source.drive_adapter,
            source.github_adapter,
            source.local_adapter,
        ),
        source_routers=SourceRouterBundle(
            web=(drive_oauth, drive_mounts, github_install, github_mounts),
            webhooks=(drive_webhook, github_webhook),
            desktop=(local_desktop,),
        ),
        extra_api_routers=(scheduler,),
    )


def _compose_worker(foundation, context: RuntimeCompositionContext) -> RuntimeComposition:
    settings = context.settings
    assert settings.vertex_config is not None
    assert settings.kipris_api_key_secret_id is not None
    assert settings.package_metadata_base_url is not None
    source = _source_runtime(foundation, settings)

    metadata = HttpPackageMetadataProvider(
        deps_dev_base_url=settings.package_metadata_base_url
    )
    model = GoogleGenAIClient(
        settings.gemini_model_id,
        vertex_config={
            "vertexai": True,
            "project": settings.gcp_project_id,
            "location": settings.vertex_config,
        },
    )
    kipris = KiprisClient(_secret(foundation, settings.kipris_api_key_secret_id))
    retriever = None
    close_callbacks = [metadata.aclose, kipris.aclose]
    if settings.rag_enabled:
        assert settings.gcp_project_id is not None
        assert settings.rag_region is not None
        assert settings.rag_corpus_id is not None
        retriever = RagEngineRetriever(
            RagEngineConfig(
                project_id=settings.gcp_project_id,
                region=settings.rag_region,
                corpus_id=settings.rag_corpus_id,
                corpus_version=settings.rag_corpus_version or "unversioned",
            )
        )
        close_callbacks.append(retriever.aclose)
    intelligence = IntelligenceFacade(
        create_analyzer_registry(
            metadata_provider=metadata,
            model_client=model,
            search_provider=kipris,
            retriever=retriever,
        )
    )
    return RuntimeComposition(
        source_adapters=(
            source.drive_adapter,
            source.github_adapter,
            source.local_adapter,
        ),
        intelligence=intelligence,
        task_authenticator=GoogleOidcTaskAuthenticator(
            audience=settings.public_base_url,
            service_account_email=TASKS_SERVICE_ACCOUNT,
        ),
        close_callbacks=tuple(close_callbacks),
    )


class _DriveChannelResolver:
    def __init__(self, runtime_store, pending_store, control_facade) -> None:
        self._runtime = runtime_store
        self._pending = pending_store
        self._control = control_facade

    async def resolve_mount(self, channel_id: str):
        runtime = await self._runtime.find_one("watch_channel_id", channel_id)
        if runtime is None:
            return None
        binding = await self._pending.get_binding_for_connection(runtime.connection_id)
        if binding is None:
            return None
        return await self._control.get_mount_ref(binding.mount_id)


class _GitHubMountResolver:
    def __init__(self, tracking_store, control_facade) -> None:
        self._tracking = tracking_store
        self._control = control_facade

    async def resolve_mounts(self, owner: str, repo: str):
        scopes = await self._tracking.find_many(
            {"owner": owner, "repo": repo},
            limit=100,
        )
        return [await self._control.get_mount_ref(scope.mount_id) for scope in scopes]


class _LocalDeviceLookup:
    def __init__(self, device_store) -> None:
        self._devices = device_store

    async def resolve(self, mount_id: str) -> LocalDeviceContext:
        binding = await self._devices.get_mount_binding(mount_id)
        if binding is None:
            raise NotFoundError(
                provider="local",
                safe_message="Local mount device binding was not found",
            )
        return LocalDeviceContext(device_id=binding.device_id, mount_handle=mount_id)


class _LocalRegistrationCallbacks:
    def __init__(self, *, devices, control_facade, runtime_store) -> None:
        self._devices = devices
        self._control = control_facade
        self._runtime = runtime_store

    async def authorize_device(self, request: Request, _resource_id: str) -> None:
        await self._devices.authenticate(request)

    async def register_device(
        self,
        request: Request,
        device_id: str,
        _device_label: str,
    ) -> None:
        device = await self._devices.authenticate(request)
        if device.device_id != device_id:
            raise HTTPException(status_code=403, detail="device identity mismatch")

    async def create_local_mount(self, request: Request, body) -> MountRegistrationResponse:
        device = await self._devices.authenticate(request)
        scope_key = stable_key(
            "local-source-scope",
            (
                device.device_id,
                body.risk_workspace_id,
                *sorted(body.include_patterns),
                "--exclude--",
                *sorted(body.exclude_patterns),
            ),
        )
        result = await self._control.register_source_metadata(
            SourceMetadataRegistrationCommand(
                registration_key=scope_key,
                actor_user_id=device.owner_user_id,
                risk_workspace_id=body.risk_workspace_id,
                source_type=SourceType.LOCAL,
                connection_key=device.device_id,
                source_workspace_key=scope_key,
                external_scope_id=f"local:{scope_key}",
                source_workspace_display_name="Local Desktop",
                mount_alias="Local Desktop",
                provider_subject=device.device_id,
                provider_account_label=None,
                credential_ref=None,
                tracking_config_safe={
                    "include_patterns": sorted(body.include_patterns),
                    "exclude_patterns": sorted(body.exclude_patterns),
                },
            )
        )
        await self._devices.bind_mount(
            device_id=device.device_id,
            risk_workspace_id=body.risk_workspace_id,
            mount_id=result.mount_id,
        )
        await self._runtime.save(
            device.device_id,
            LocalRuntime(
                device_id=device.device_id,
                mount_handle=result.mount_id,
                status=LocalConnectionStatus.ONLINE,
            ),
        )
        return MountRegistrationResponse(
            server_mount_id=result.mount_id,
            source_workspace_id=result.source_workspace_id,
        )


def _secret(foundation, secret_id: str) -> str:
    reader = foundation.clients.runtime_secrets
    if reader is None:
        raise SettingsError("Secret Manager runtime secret reader is unavailable")
    return reader.access(secret_id)


__all__ = ["build_google_cloud_runtime_composer"]
