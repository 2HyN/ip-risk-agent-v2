"""Drive / GitHub provider 조립.

Source Plane 은 provider client 와 라우터를 모두 갖고 있지만, 그것들을 잇는
조회 포트와 운영 저장소는 Integration 이 채운다. 그 조립이 여기 있다.

자격증명이 없으면 **아무것도 만들지 않는다.** 반쯤 조립된 adapter 를 남겨
런타임에 실패하게 두지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iprisk_contracts.common import SourceType

from ip_risk_agent.connectors.common.runtime_store import (
    DriveRuntime,
    GitHubRuntime,
    InMemoryRuntimeStore,
)
from ip_risk_agent.connectors.github.adapter import GitHubAdapter
from ip_risk_agent.connectors.github.client import GitHubAppProviderFactory
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope
from ip_risk_agent.connectors.github.webhook_processor import GitHubWebhookProcessor
from ip_risk_agent.connectors.google_drive.adapter import GoogleDriveAdapter
from ip_risk_agent.connectors.google_drive.client import GoogleDriveProviderFactory
from ip_risk_agent.connectors.google_drive.tracking_scope import DriveTrackingScope

from .gcp.stores import (
    TRACKING_SCOPE_COLLECTION,
    BoundDriveChannelMountResolver,
    BoundDriveConnectionCredentialLookup,
    BoundDriveConnectionLookup,
    BoundGitHubConnectionInstallationLookup,
    BoundGitHubConnectionLookup,
    BoundGitHubMountResolver,
    FirestoreMountBindingStore,
    FirestoreRuntimeStore,
)
from .settings import Settings


@dataclass(frozen=True, slots=True)
class DriveProviderBundle:
    """Drive 라우터들이 필요로 하는 것 전부."""

    provider_factory: Any
    connection_lookup: Any
    credential_lookup: Any
    channel_resolver: Any
    tracking_scope_store: Any
    runtime_store: Any
    adapter: GoogleDriveAdapter


@dataclass(frozen=True, slots=True)
class GitHubProviderBundle:
    """GitHub 라우터들이 필요로 하는 것 전부."""

    provider_factory: Any
    connection_lookup: Any
    installation_lookup: Any
    mount_resolver: Any
    tracking_scope_store: Any
    runtime_store: Any
    adapter: GitHubAdapter
    webhook_processor: GitHubWebhookProcessor | None


def _runtime_store(
    model: type,
    settings: Settings,
    *,
    collection: str,
    bindings: FirestoreMountBindingStore | None,
) -> Any:
    """Firestore 가 있으면 그것을, 없으면 프로세스 메모리를 쓴다."""
    control = settings.control
    if bindings is not None and control.gcp_project_id:
        return FirestoreRuntimeStore(
            model,
            project_id=control.gcp_project_id,
            collection=collection,
            database=control.firestore_database or "(default)",
        )
    return InMemoryRuntimeStore()


def build_drive_bundle(
    settings: Settings,
    *,
    credential_vault: Any,
    bindings: FirestoreMountBindingStore | None,
    connection_lookup: Any | None = None,
    credential_lookup: Any | None = None,
    channel_resolver: Any | None = None,
) -> DriveProviderBundle | None:
    """Drive 자격증명이 있을 때만 조립한다."""
    source = settings.source
    if not source.drive_configured:
        return None

    if bindings is None and (
        connection_lookup is None or credential_lookup is None or channel_resolver is None
    ):
        # Firestore 없이 Drive 를 완전히 조립할 수단이 없다. 반쯤 만들지 않는다.
        return None

    resolved_connection = connection_lookup or BoundDriveConnectionLookup(bindings)
    resolved_credential = credential_lookup or BoundDriveConnectionCredentialLookup(
        bindings
    )
    resolved_channel = channel_resolver or BoundDriveChannelMountResolver(bindings)

    tracking_scope_store = _runtime_store(
        DriveTrackingScope,
        settings,
        collection=f"{TRACKING_SCOPE_COLLECTION}_drive",
        bindings=bindings,
    )
    runtime_store = _runtime_store(
        DriveRuntime, settings, collection="integration_drive_runtime", bindings=bindings
    )

    provider_factory = GoogleDriveProviderFactory(
        source.drive_client_id or "", source.drive_client_secret or ""
    )
    adapter = GoogleDriveAdapter(
        provider_factory=provider_factory,
        credential_vault=credential_vault,
        connection_lookup=resolved_connection,
        tracking_scope_store=tracking_scope_store,
        runtime_store=runtime_store,
    )
    return DriveProviderBundle(
        provider_factory=provider_factory,
        connection_lookup=resolved_connection,
        credential_lookup=resolved_credential,
        channel_resolver=resolved_channel,
        tracking_scope_store=tracking_scope_store,
        runtime_store=runtime_store,
        adapter=adapter,
    )


def build_github_bundle(
    settings: Settings,
    *,
    bindings: FirestoreMountBindingStore | None,
    connection_lookup: Any | None = None,
    installation_lookup: Any | None = None,
    mount_resolver: Any | None = None,
) -> GitHubProviderBundle | None:
    """GitHub App 자격증명이 있을 때만 조립한다."""
    source = settings.source
    if not source.github_configured or not source.github_app_private_key:
        return None

    if bindings is None and (
        connection_lookup is None
        or installation_lookup is None
        or mount_resolver is None
    ):
        return None

    resolved_connection = connection_lookup or BoundGitHubConnectionLookup(bindings)
    resolved_installation = (
        installation_lookup or BoundGitHubConnectionInstallationLookup(bindings)
    )
    resolved_mounts = mount_resolver or BoundGitHubMountResolver(bindings)

    tracking_scope_store = _runtime_store(
        GitHubTrackingScope,
        settings,
        collection=f"{TRACKING_SCOPE_COLLECTION}_github",
        bindings=bindings,
    )
    runtime_store = _runtime_store(
        GitHubRuntime,
        settings,
        collection="integration_github_runtime",
        bindings=bindings,
    )

    provider_factory = GitHubAppProviderFactory(
        app_id=source.github_app_id or "",
        private_key_pem=source.github_app_private_key or "",
    )
    adapter = GitHubAdapter(
        provider_factory=provider_factory,
        connection_lookup=resolved_connection,
        tracking_scope_store=tracking_scope_store,
    )

    webhook_processor = None
    if source.github_webhook_secret:
        # webhook 서명 검증 없이 processor 를 만들면 위조 요청을 받아들이게 된다.
        # secret 이 없으면 아예 만들지 않는다.
        webhook_processor = GitHubWebhookProcessor(
            provider_factory=provider_factory,
            connection_lookup=resolved_connection,
            tracking_scope_store=tracking_scope_store,
            runtime_store=runtime_store,
            webhook_secret=source.github_webhook_secret,
        )

    return GitHubProviderBundle(
        provider_factory=provider_factory,
        connection_lookup=resolved_connection,
        installation_lookup=resolved_installation,
        mount_resolver=resolved_mounts,
        tracking_scope_store=tracking_scope_store,
        runtime_store=runtime_store,
        adapter=adapter,
        webhook_processor=webhook_processor,
    )


def source_adapters(
    drive: DriveProviderBundle | None, github: GitHubProviderBundle | None
) -> dict[SourceType, Any]:
    """워커 파이프라인에 넘길 provider 별 ``SourceAdapter``.

    Local 은 Desktop 이 staging 에 올린 내용을 쓰므로 별도 adapter 조립이
    Integration 몫이 아니다.
    """
    adapters: dict[SourceType, Any] = {}
    if drive is not None:
        adapters[SourceType.GOOGLE_DRIVE] = drive.adapter
    if github is not None:
        adapters[SourceType.GITHUB] = github.adapter
    return adapters


__all__ = [
    "DriveProviderBundle",
    "GitHubProviderBundle",
    "build_drive_bundle",
    "build_github_bundle",
    "source_adapters",
]
