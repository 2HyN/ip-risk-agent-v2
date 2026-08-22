"""Risk Workspace 의 canonical 데이터를 Firestore 에서 지운다.

트랜잭션을 쓰지 않는다. Firestore 트랜잭션은 쓰기 개수에 한계가 있고, workspace
하나의 문서 수는 그 한계를 쉽게 넘는다. 대신 **다시 불러도 안전하게** 만들어서
도중에 실패하면 이어서 마무리되게 한다. workspace 문서를 마지막에 지우는 것이 그
장치다 — 그것이 남아 있으면 삭제가 끝나지 않았다는 뜻이다.

``InMemoryWorkspaceEraser`` 와 **같은 순서**로 지운다. 순서가 갈리면 시험이
통과해도 프로덕션이 다르게 동작한다.
"""

from __future__ import annotations

from collections.abc import Iterable

from .schema import (
    ANALYSIS_JOBS,
    ARTIFACTS,
    ARTIFACT_STATES,
    AUDIT_EVENTS,
    CHANGE_EVENTS,
    MEMBERSHIPS,
    NOTIFICATIONS,
    RISKS,
    RISK_EVENTS,
    RISK_EVIDENCE,
    RISK_WORKSPACES,
    SOURCE_ACCESS_EVENTS,
    SOURCE_WORKSPACES,
    WORKSPACE_MOUNTS,
)

#: ``risk_workspace_id`` 필드 하나로 바로 고를 수 있는 컬렉션.
_WORKSPACE_SCOPED = (
    MEMBERSHIPS,
    WORKSPACE_MOUNTS,
    ARTIFACTS,
    CHANGE_EVENTS,
    RISKS,
    AUDIT_EVENTS,
    SOURCE_ACCESS_EVENTS,
    NOTIFICATIONS,
)

#: 고유키 색인이 함께 사는 컬렉션. 소유 문서가 사라지면 색인도 지운다.
#: 남기면 같은 alias 나 risk key 를 다시 쓸 수 없어, 사용자에게는 "지워지지 않은
#: 것" 과 구별되지 않는다.
_UNIQUE_KEY_HOSTS = (
    RISKS,
    ARTIFACTS,
    WORKSPACE_MOUNTS,
    CHANGE_EVENTS,
    SOURCE_WORKSPACES,
    RISK_WORKSPACES,
)

_UNIQUE_KEY_RECORD = "unique_key"


class FirestoreWorkspaceEraser:
    def __init__(self, client) -> None:
        self._client = client

    async def erase(self, risk_workspace_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}

        mounts = await self._ids_where(WORKSPACE_MOUNTS, risk_workspace_id)
        artifacts = await self._ids_where(ARTIFACTS, risk_workspace_id)
        changes = await self._ids_where(CHANGE_EVENTS, risk_workspace_id)
        risks = await self._ids_where(RISKS, risk_workspace_id)

        source_workspace_ids: set[str] = set()
        for mount_id in mounts:
            data = await self._get(WORKSPACE_MOUNTS, mount_id)
            if data and (value := data.get("source_workspace_id")):
                source_workspace_ids.add(str(value))

        owned_ids = set(mounts) | set(artifacts) | set(changes) | set(risks)

        # 1. 참조로만 찾을 수 있는 자식.
        await self._delete(counts, ARTIFACT_STATES, artifacts)
        await self._delete(
            counts,
            ANALYSIS_JOBS,
            await self._scan(
                ANALYSIS_JOBS,
                lambda data: str(data.get("change_event_id", "")) in set(changes)
                or str(data.get("artifact_id", "")) in set(artifacts),
            ),
        )
        for child in (RISK_EVIDENCE, RISK_EVENTS):
            await self._delete(
                counts,
                child,
                await self._scan(
                    child, lambda data: str(data.get("risk_id", "")) in set(risks)
                ),
            )

        # 2. workspace 범위 canonical.
        for collection in _WORKSPACE_SCOPED:
            await self._delete(
                counts, collection, await self._ids_where(collection, risk_workspace_id)
            )

        # 3. 이 workspace 의 mount 만 참조하던 source workspace.
        orphaned = []
        for source_workspace_id in sorted(source_workspace_ids):
            remaining = await self._scan(
                WORKSPACE_MOUNTS,
                lambda data, target=source_workspace_id: (
                    str(data.get("source_workspace_id", "")) == target
                ),
            )
            if not remaining:
                orphaned.append(source_workspace_id)
        await self._delete(counts, SOURCE_WORKSPACES, orphaned)
        owned_ids |= set(orphaned)
        owned_ids.add(risk_workspace_id)

        # 4. 소유 문서가 사라진 고유키 색인.
        for collection in _UNIQUE_KEY_HOSTS:
            await self._delete(
                counts,
                collection,
                await self._scan(
                    collection,
                    lambda data: data.get("record_kind") == _UNIQUE_KEY_RECORD
                    and str(data.get("owner_document_id", "")) in owned_ids,
                ),
                label=f"{collection}:unique_key",
            )

        # 5. 마지막에 workspace 자신. 이것이 남아 있으면 삭제가 끝나지 않은 것이다.
        await self._delete(counts, RISK_WORKSPACES, [risk_workspace_id])
        return counts

    # --------------------------------------------------------------- 내부

    async def _get(self, collection: str, document_id: str):
        snapshot = await self._client.collection(collection).document(document_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def _ids_where(self, collection: str, risk_workspace_id: str) -> list[str]:
        from google.cloud.firestore_v1.base_query import (  # noqa: PLC0415
            FieldFilter,
        )

        stream = (
            self._client.collection(collection)
            .where(filter=FieldFilter("risk_workspace_id", "==", risk_workspace_id))
            .stream()
        )
        return [document.id async for document in stream]

    async def _scan(self, collection: str, predicate) -> list[str]:
        """훑어서 고른다. 색인 없이 걸러야 하는 조건에만 쓴다."""
        matched: list[str] = []
        async for document in self._client.collection(collection).stream():
            if predicate(document.to_dict() or {}):
                matched.append(document.id)
        return matched

    async def _delete(
        self,
        counts: dict[str, int],
        collection: str,
        document_ids: Iterable[str],
        *,
        label: str | None = None,
    ) -> None:
        removed = 0
        for document_id in document_ids:
            await self._client.collection(collection).document(document_id).delete()
            removed += 1
        if removed:
            key = label or collection
            counts[key] = counts.get(key, 0) + removed


__all__ = ["FirestoreWorkspaceEraser"]
