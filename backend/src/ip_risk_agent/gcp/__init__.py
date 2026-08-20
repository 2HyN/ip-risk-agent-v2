"""Production Google Cloud adapters owned by the integration layer."""

from .cloud_tasks import CloudTasksEnqueuer
from .foundation import (
    GoogleCloudClients,
    GoogleCloudFoundation,
    SecretManagerRuntimeSecretReader,
    build_google_cloud_foundation,
)
from .identity import GoogleOidcTaskAuthenticator
from .operational_firestore import (
    FirestoreDeviceAuthStore,
    FirestoreOAuthStateStore,
    FirestorePendingConnectionStore,
    FirestoreRuntimeStore,
    GoogleOperationalFirestoreBackend,
)
from .secret_vault import SecretManagerCredentialVault
from .staging import CloudStorageLocalStagingStore

__all__ = [
    "CloudStorageLocalStagingStore",
    "CloudTasksEnqueuer",
    "FirestoreDeviceAuthStore",
    "FirestoreOAuthStateStore",
    "FirestorePendingConnectionStore",
    "FirestoreRuntimeStore",
    "GoogleOidcTaskAuthenticator",
    "GoogleCloudClients",
    "GoogleCloudFoundation",
    "GoogleOperationalFirestoreBackend",
    "SecretManagerCredentialVault",
    "SecretManagerRuntimeSecretReader",
    "build_google_cloud_foundation",
]
