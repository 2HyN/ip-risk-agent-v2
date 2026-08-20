"""Explicit construction of durable Google Cloud foundation adapters.

No client is created at import time.  The public entrypoint is deliberately
small so provider/router composition can share exactly one Firestore client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from google.cloud import firestore, secretmanager, storage, tasks_v2

from ip_risk_agent.composition.settings import (
    AppRole,
    RuntimeProfile,
    Settings,
    SettingsError,
)
from ip_risk_agent.persistence.core_firestore import FirestoreControlUnitOfWorkFactory

from .cloud_tasks import CloudTasksEnqueuer
from .operational_firestore import (
    FirestoreDeviceAuthStore,
    GoogleOperationalFirestoreBackend,
)
from .secret_vault import SecretManagerCredentialVault
from .staging import CloudStorageLocalStagingStore


@dataclass(slots=True)
class GoogleCloudClients:
    firestore: object
    secret_manager: object
    cloud_tasks: object | None
    storage: object
    runtime_secrets: "SecretManagerRuntimeSecretReader | None" = None

    @classmethod
    def create(cls, settings: Settings) -> "GoogleCloudClients":
        assert settings.gcp_project_id is not None
        assert settings.firestore_database is not None
        cloud_tasks = (
            tasks_v2.CloudTasksAsyncClient()
            if settings.role is AppRole.API
            else None
        )
        return cls(
            firestore=firestore.AsyncClient(
                project=settings.gcp_project_id,
                database=settings.firestore_database,
            ),
            secret_manager=secretmanager.SecretManagerServiceAsyncClient(),
            cloud_tasks=cloud_tasks,
            storage=storage.Client(project=settings.gcp_project_id),
            runtime_secrets=SecretManagerRuntimeSecretReader(
                client=secretmanager.SecretManagerServiceClient(),
                project_id=settings.gcp_project_id,
            ),
        )


class SecretManagerRuntimeSecretReader:
    """Read deployment-owned static secrets through ADC without key files."""

    def __init__(self, *, client, project_id: str) -> None:
        self._client = client
        self._parent = f"projects/{project_id}/secrets"

    def access(self, secret_id: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,255}", secret_id) is None:
            raise SettingsError("Secret Manager secret ID is invalid")
        response = self._client.access_secret_version(
            name=f"{self._parent}/{secret_id}/versions/latest"
        )
        value = bytes(response.payload.data).decode("utf-8")
        if not value:
            raise SettingsError("Secret Manager secret version is empty")
        return value

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()


@dataclass(slots=True)
class GoogleCloudFoundation:
    clients: GoogleCloudClients
    unit_of_work_factory: FirestoreControlUnitOfWorkFactory
    operational_backend: GoogleOperationalFirestoreBackend
    task_enqueuer: CloudTasksEnqueuer | None
    credential_vault: SecretManagerCredentialVault
    staging_store: CloudStorageLocalStagingStore
    device_auth_store: FirestoreDeviceAuthStore

    def container_overrides(self, **values):
        """Return durable base overrides; provider routers remain explicit inputs."""
        from ip_risk_agent.composition.container import ContainerOverrides

        if self.clients is None:  # pragma: no cover - defensive dataclass invariant
            raise RuntimeError("Google Cloud clients are unavailable")
        task_authenticator = values.pop("task_authenticator", None)
        additional_close_callbacks = tuple(values.pop("close_callbacks", ()))
        return ContainerOverrides(
            unit_of_work_factory=self.unit_of_work_factory,
            task_enqueuer=self.task_enqueuer,
            device_auth_store=self.device_auth_store,
            task_authenticator=task_authenticator,
            close_callbacks=(*additional_close_callbacks, self.close),
            **values,
        )

    async def close(self) -> None:
        for client in (
            self.clients.firestore,
            self.clients.secret_manager,
            self.clients.cloud_tasks,
            self.clients.storage,
            self.clients.runtime_secrets,
        ):
            if client is None:
                continue
            close = getattr(client, "close", None)
            if close is None:
                continue
            result = close()
            if hasattr(result, "__await__"):
                await result


def build_google_cloud_foundation(
    settings: Settings,
    *,
    clients: GoogleCloudClients | None = None,
) -> GoogleCloudFoundation:
    settings.validate()
    if settings.profile is not RuntimeProfile.PRODUCTION:
        raise SettingsError("Google Cloud foundation is production-only")
    required = (
        settings.gcp_project_id,
        settings.firestore_database,
        settings.local_staging_bucket,
    )
    if any(value is None for value in required):
        raise SettingsError("Google Cloud foundation settings are incomplete")

    clients = clients or GoogleCloudClients.create(settings)
    operational = GoogleOperationalFirestoreBackend(clients.firestore)
    device_store = FirestoreDeviceAuthStore(operational)
    task_enqueuer = None
    if settings.role is AppRole.API:
        if clients.cloud_tasks is None:
            raise SettingsError("production API Cloud Tasks client is unavailable")
        assert settings.cloud_tasks_location is not None
        assert settings.cloud_tasks_queue is not None
        assert settings.analysis_worker_url is not None
        assert settings.cloud_tasks_service_account is not None
        task_enqueuer = CloudTasksEnqueuer(
            client=clients.cloud_tasks,
            project_id=settings.gcp_project_id,
            location=settings.cloud_tasks_location,
            queue=settings.cloud_tasks_queue,
            worker_base_url=settings.analysis_worker_url,
            service_account_email=settings.cloud_tasks_service_account,
        )
    return GoogleCloudFoundation(
        clients=clients,
        unit_of_work_factory=FirestoreControlUnitOfWorkFactory.from_client(
            clients.firestore
        ),
        operational_backend=operational,
        task_enqueuer=task_enqueuer,
        credential_vault=SecretManagerCredentialVault(
            client=clients.secret_manager,
            project_id=settings.gcp_project_id,
            secret_prefix=settings.source_credential_secret_prefix,
        ),
        staging_store=CloudStorageLocalStagingStore(
            client=clients.storage,
            bucket_name=settings.local_staging_bucket,
        ),
        device_auth_store=device_store,
    )


__all__ = [
    "GoogleCloudClients",
    "GoogleCloudFoundation",
    "SecretManagerRuntimeSecretReader",
    "build_google_cloud_foundation",
]
