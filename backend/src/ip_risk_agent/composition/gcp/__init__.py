"""GCP 자원 어댑터.

각 Plane 이 Protocol 로만 요구한 포트의 실물 구현이다. 이 패키지 밖에서는
GCP SDK 를 import 하지 않는다 — 그래야 자격증명 없는 환경에서도 앱이 뜬다.

모든 SDK import 는 함수 안에서 지연 수행한다. 모듈 import 만으로는 GCP 를
건드리지 않으므로 테스트가 자유롭게 불러올 수 있다.
"""

from .queue import CloudTasksEnqueuer, task_name_for
from .relay import (
    ChangeRelayStore,
    FirestoreChangeRelayStore,
    InMemoryChangeRelayStore,
)
from .secrets import SecretManagerCredentialVault, secret_id_for
from .state import FirestoreOAuthStateStore
from .storage import GcsLocalStagingStore
from .stores import (
    BoundDriveChannelMountResolver,
    BoundDriveConnectionCredentialLookup,
    BoundDriveConnectionLookup,
    BoundGitHubConnectionInstallationLookup,
    BoundGitHubConnectionLookup,
    BoundGitHubMountResolver,
    FirestoreMountBindingStore,
    FirestoreRuntimeStore,
)

__all__ = [
    "BoundDriveChannelMountResolver",
    "BoundDriveConnectionCredentialLookup",
    "BoundDriveConnectionLookup",
    "BoundGitHubConnectionInstallationLookup",
    "BoundGitHubConnectionLookup",
    "BoundGitHubMountResolver",
    "ChangeRelayStore",
    "CloudTasksEnqueuer",
    "FirestoreChangeRelayStore",
    "FirestoreMountBindingStore",
    "FirestoreOAuthStateStore",
    "FirestoreRuntimeStore",
    "GcsLocalStagingStore",
    "InMemoryChangeRelayStore",
    "SecretManagerCredentialVault",
    "secret_id_for",
    "task_name_for",
]
