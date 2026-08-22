"""Risk Workspace 의 operational 데이터를 Firestore 에서 지운다.

canonical 과 나눠 둔 이유는 저장 위치도 수명도 다르기 때문이다. operational 기록은
provider 연결의 런타임 상태(감시 커서, 추적 범위, 기기 자격증명)이고 canonical 이
아니다. 그래서 지우는 주체도 따로 둔다.

**canonical 보다 먼저** 지운다. canonical 을 먼저 지우면 실패했을 때 남은 operational
기록이 가리킬 곳을 잃는다. 반대 순서라면 workspace 는 아직 ``DELETING`` 으로 남아
있어 다시 시도할 수 있다.

지우지 않는 것 — Secret Manager 의 provider credential. 다른 workspace 가 같은
연결을 쓸 수 있어 여기서 판단할 수 없다. 필요하면 따로 지운다.
"""

from __future__ import annotations

from collections.abc import Mapping

#: mount / connection 참조로 걸러야 하는 컬렉션. record 아래에 값이 들어 있다.
OPERATIONAL_COLLECTIONS = (
    "source_operational_mount_bindings",
    "source_operational_pending_connections",
    "source_operational_drive_runtime",
    "source_operational_drive_tracking",
    "source_operational_github_runtime",
    "source_operational_github_tracking",
    "source_operational_local_runtime",
    "source_operational_device_mounts",
    "source_operational_devices",
    "source_operational_device_challenges",
    "source_operational_device_credentials",
    "source_operational_oauth_states",
)


class FirestoreOperationalEraser:
    def __init__(self, client, *, collections=OPERATIONAL_COLLECTIONS) -> None:
        self._client = client
        self._collections = tuple(collections)

    async def erase(self, risk_workspace_id: str) -> dict[str, int]:
        mount_ids, connection_ids = await self._references(risk_workspace_id)
        counts: dict[str, int] = {}
        for collection in self._collections:
            removed = 0
            async for document in self._client.collection(collection).stream():
                data = document.to_dict() or {}
                record = data.get("record")
                record = record if isinstance(record, Mapping) else {}
                if not _belongs(
                    data, record, risk_workspace_id, mount_ids, connection_ids
                ):
                    continue
                await self._client.collection(collection).document(document.id).delete()
                removed += 1
            if removed:
                counts[collection] = removed
        return counts

    async def _references(self, risk_workspace_id: str) -> tuple[set[str], set[str]]:
        """canonical mount 에서 참조 값을 미리 모은다.

        canonical 이 아직 살아 있을 때 불러야 한다. 그래서 이 eraser 가 먼저다.

        **connection 은 workspace 소유가 아니다.** Drive 연결은 계정 단위라 여러
        workspace 의 mount 가 같은 것을 공유한다. 그래서 connection 으로 걸린
        operational 기록(감시 채널, 변경 커서 같은 것)은 **다른 workspace 가 더 이상
        쓰지 않을 때만** 지운다. 그러지 않으면 workspace 하나를 지웠는데 다른
        workspace 의 변경 감지가 조용히 끊긴다.
        """
        mount_ids: set[str] = set()
        ours: set[str] = set()
        used_by_others: set[str] = set()
        async for document in self._client.collection("workspace_mounts").stream():
            data = document.to_dict() or {}
            connection_id = data.get("source_connection_id")
            if data.get("risk_workspace_id") == risk_workspace_id:
                mount_ids.add(document.id)
                if connection_id:
                    ours.add(str(connection_id))
            elif connection_id:
                used_by_others.add(str(connection_id))
        return mount_ids, ours - used_by_others


def _belongs(
    data: Mapping[str, object],
    record: Mapping[str, object],
    risk_workspace_id: str,
    mount_ids: set[str],
    connection_ids: set[str],
) -> bool:
    if (
        record.get("risk_workspace_id") == risk_workspace_id
        or data.get("risk_workspace_id") == risk_workspace_id
    ):
        return True
    if str(record.get("mount_id", "")) in mount_ids or str(
        data.get("mount_id", "")
    ) in mount_ids:
        return True
    # connection_ids 에는 다른 workspace 가 더 이상 쓰지 않는 것만 들어 있다.
    for key in ("connection_id", "canonical_connection_id"):
        for holder in (record, data):
            value = holder.get(key)
            if value and str(value) in connection_ids:
                return True
    return False


__all__ = ["FirestoreOperationalEraser", "OPERATIONAL_COLLECTIONS"]
