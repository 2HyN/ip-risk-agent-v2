"""Source Plane 전용 operational state 저장소.

Master Spec 38번 / Agent 2 Spec 5번(Source Operational Store)을 코드로
옮긴 것: canonical Firestore Risk/Membership/Review state와 분리된,
connector 자신의 운영 상태만 다룬다. Risk/Review 관련 필드는 여기 절대
넣지 않는다.

실제 저장 backend(Firestore isolated collection 등)는 Integration Agent가
wiring 한다. 여기서는 설계도(Protocol)와 In-Memory 가짜 구현만 제공한다.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, Protocol, TypeVar

from pydantic import AwareDatetime, Field

from iprisk_contracts.common import SafeMetadata, StrictModel


class WebhookStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class LocalConnectionStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class DriveRuntime(StrictModel):
    """Agent 2 Spec 5번 DriveRuntime."""

    connection_id: str
    change_cursor: str | None = None
    watch_channel_id: str | None = None
    watch_resource_id: str | None = None
    watch_expiry: AwareDatetime | None = None
    reconciliation_lease: str | None = None


class GitHubRuntime(StrictModel):
    """Agent 2 Spec 5번 GitHubRuntime."""

    connection_id: str
    installation_id: str
    repository_id: str
    tracked_branch: str
    webhook_status: WebhookStatus = WebhookStatus.INACTIVE
    last_seen_delivery_id: str | None = None


class LocalRuntime(StrictModel):
    """Agent 2 Spec 5번 LocalRuntime."""

    device_id: str
    mount_handle: str
    status: LocalConnectionStatus = LocalConnectionStatus.UNKNOWN
    last_heartbeat: AwareDatetime | None = None
    staging_metadata: SafeMetadata = Field(default_factory=dict)


RuntimeRecord = TypeVar("RuntimeRecord")


class RuntimeStore(Protocol[RuntimeRecord]):
    """provider 하나(Drive 전용/GitHub 전용/Local 전용)의 operational state
    저장소가 지켜야 할 최소 계약. key는 provider별로 자연스러운 식별자를
    호출하는 쪽(adapter)이 정한다 (예: Drive는 connection_id, GitHub는
    f"{installation_id}:{repository_id}")."""

    async def load(self, key: str) -> RuntimeRecord | None: ...

    async def save(self, key: str, record: RuntimeRecord) -> None: ...

    async def delete(self, key: str) -> None: ...


class InMemoryRuntimeStore(Generic[RuntimeRecord]):
    """개발/테스트 전용 가짜 저장소. 프로세스 재시작하면 다 사라진다."""

    def __init__(self) -> None:
        self._store: dict[str, RuntimeRecord] = {}

    async def load(self, key: str) -> RuntimeRecord | None:
        return self._store.get(key)

    async def save(self, key: str, record: RuntimeRecord) -> None:
        self._store[key] = record

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
