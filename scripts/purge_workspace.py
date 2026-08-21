"""테스트용 Risk Workspace 완전 삭제.

제품의 삭제 정책은 아직 정해지지 않았다. 제품 경로의 `DELETE /workspaces/{id}` 는
상태를 `DELETING` 으로 바꾸는 soft delete 이고 데이터를 지우지 않는다. 이 도구는
**반복 테스트를 위해** 한 workspace 의 흔적을 canonical/operational 양쪽에서
지운다.

배포된 앱에 삭제 표면을 만들지 않으려고 API 가 아니라 스크립트로 둔다. 실행에는
Firestore 접근 권한이 필요하다 (`gcloud auth application-default login`).

    python scripts/purge_workspace.py --workspace-id workspace-XXXX          # dry-run
    python scripts/purge_workspace.py --workspace-id workspace-XXXX --confirm

지우지 않는 것:

* `users` — 계정은 workspace 소유가 아니다
* Secret Manager 의 동적 provider credential — 다른 workspace 가 같은 provider
  연결을 쓸 수 있다. 필요하면 `gcloud secrets delete` 로 따로 지운다
* Drive/GitHub 쪽 실제 파일 — 이 도구는 우리 저장소만 건드린다
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ip_risk_agent.gcp_contract import FIRESTORE_DATABASE, PROJECT_ID

# canonical: 최상위 risk_workspace_id 로 바로 찾을 수 있는 것
WORKSPACE_SCOPED = (
    "memberships",
    "workspace_mounts",
    "artifacts",
    "change_events",
    "risks",
    "audit_events",
    "source_access_events",
    "notifications",
)

# operational: record.* 아래 값으로 걸러야 하는 것
OPERATIONAL = (
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


def _client(database: str):
    from google.cloud import firestore  # noqa: PLC0415 - 지연 import

    return firestore.AsyncClient(project=PROJECT_ID, database=database)


async def _ids_where(client, collection: str, field: str, value: str) -> list[str]:
    stream = client.collection(collection).where(field, "==", value).stream()
    return [document.id async for document in stream]


async def _scan(client, collection: str, predicate) -> list[str]:
    """작은 컬렉션은 훑어서 고른다. 테스트 규모에서만 쓴다."""
    matched: list[str] = []
    async for document in client.collection(collection).stream():
        data = document.to_dict() or {}
        record = data.get("record")
        if predicate(data, record if isinstance(record, dict) else {}):
            matched.append(document.id)
    return matched


async def _delete(client, collection: str, ids: list[str], *, confirm: bool) -> int:
    if not ids:
        return 0
    if confirm:
        for document_id in ids:
            await client.collection(collection).document(document_id).delete()
    return len(ids)


async def purge(workspace_id: str, *, database: str, confirm: bool) -> dict[str, int]:
    client = _client(database)
    counts: dict[str, int] = {}
    try:
        # 1. 파생 대상을 지우기 전에 참조를 먼저 모은다.
        mount_ids = await _ids_where(
            client, "workspace_mounts", "risk_workspace_id", workspace_id
        )
        artifact_ids = await _ids_where(
            client, "artifacts", "risk_workspace_id", workspace_id
        )
        change_ids = await _ids_where(
            client, "change_events", "risk_workspace_id", workspace_id
        )
        risk_ids = await _ids_where(client, "risks", "risk_workspace_id", workspace_id)

        source_workspace_ids: set[str] = set()
        connection_ids: set[str] = set()
        for mount_id in mount_ids:
            snapshot = await client.collection("workspace_mounts").document(mount_id).get()
            data = snapshot.to_dict() or {}
            if value := data.get("source_workspace_id"):
                source_workspace_ids.add(str(value))
            if value := data.get("source_connection_id"):
                connection_ids.add(str(value))

        # 2. 참조로만 찾을 수 있는 자식 레코드.
        counts["artifact_states"] = await _delete(
            client, "artifact_states", artifact_ids, confirm=confirm
        )
        counts["analysis_jobs"] = await _delete(
            client,
            "analysis_jobs",
            await _scan(
                client,
                "analysis_jobs",
                lambda data, _r: str(data.get("change_event_id", "")) in set(change_ids)
                or str(data.get("artifact_id", "")) in set(artifact_ids),
            ),
            confirm=confirm,
        )
        for child in ("risk_evidence", "risk_events"):
            counts[child] = await _delete(
                client,
                child,
                await _scan(
                    client,
                    child,
                    lambda data, _r: str(data.get("risk_id", "")) in set(risk_ids),
                ),
                confirm=confirm,
            )

        # 3. workspace 범위 canonical.
        for collection in WORKSPACE_SCOPED:
            counts[collection] = await _delete(
                client,
                collection,
                await _ids_where(client, collection, "risk_workspace_id", workspace_id),
                confirm=confirm,
            )
        counts["invitations"] = await _delete(
            client,
            "invitations",
            await _ids_where(client, "invitations", "risk_workspace_id", workspace_id),
            confirm=confirm,
        )

        # 4. 이 workspace 의 mount 만 참조하던 source workspace.
        orphaned: list[str] = []
        for source_workspace_id in sorted(source_workspace_ids):
            others = await _scan(
                client,
                "workspace_mounts",
                lambda data, _r, target=source_workspace_id: (
                    str(data.get("source_workspace_id", "")) == target
                ),
            )
            if not others:  # 위에서 이미 지웠으면 남은 참조가 없다.
                orphaned.append(source_workspace_id)
        counts["source_workspaces"] = await _delete(
            client, "source_workspaces", orphaned, confirm=confirm
        )

        # 5. operational. mount/workspace/connection 중 하나라도 걸리면 지운다.
        mount_set, connection_set = set(mount_ids), set(connection_ids)
        for collection in OPERATIONAL:
            counts[collection] = await _delete(
                client,
                collection,
                await _scan(
                    client,
                    collection,
                    lambda data, record: (
                        record.get("risk_workspace_id") == workspace_id
                        or data.get("risk_workspace_id") == workspace_id
                        or str(record.get("mount_id", "")) in mount_set
                        or str(data.get("mount_id", "")) in mount_set
                        or str(record.get("connection_id", "")) in connection_set
                        or str(data.get("canonical_connection_id", "")) in connection_set
                    ),
                ),
                confirm=confirm,
            )

        # 6. 마지막으로 workspace 자체.
        counts["risk_workspaces"] = await _delete(
            client, "risk_workspaces", [workspace_id], confirm=confirm
        )
    finally:
        client.close()
    return counts


def validate_target(workspace_id: str, database: str) -> str | None:
    """지우기 전에 대상을 검증한다. 문제가 있으면 사유를, 없으면 ``None`` 을 준다.

    v1 운영 DB 가 같은 project 안에 `(default)` 로 있고, Firestore 도구는 대부분
    그것을 기본값으로 쓴다. 그래서 database 확인이 이 도구의 가장 중요한 안전장치다.
    """
    if database != FIRESTORE_DATABASE:
        return f"refusing to touch database {database!r}"
    if not workspace_id.startswith("workspace-"):
        return "workspace id must start with 'workspace-'"
    # canonical 자식 id 는 `workspace-mount:v1:...` 처럼 접두사를 공유한다.
    # 그것을 workspace 로 착각하면 엉뚱한 범위를 훑는다.
    if ":" in workspace_id:
        return f"{workspace_id!r} is not a workspace id"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--database", default=FIRESTORE_DATABASE)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="실제로 지운다. 없으면 셀 뿐이고 아무것도 바꾸지 않는다.",
    )
    args = parser.parse_args()

    if problem := validate_target(args.workspace_id, args.database):
        print(f"STOP: {problem}", file=sys.stderr)
        return 2

    counts = asyncio.run(
        purge(args.workspace_id, database=args.database, confirm=args.confirm)
    )
    mode = "deleted" if args.confirm else "would delete (dry-run)"
    total = sum(counts.values())
    for collection, count in sorted(counts.items()):
        if count:
            print(f"  {collection:<45} {count}")
    print(f"{mode}: {total} documents in {args.database}")
    if not args.confirm:
        print("re-run with --confirm to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
