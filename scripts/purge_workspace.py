"""테스트용 Risk Workspace 완전 삭제.

제품 경로(`DELETE /workspaces/{id}`)도 2026-08-22 부터 **전체 말소**다. 이 도구는
그것과 **같은 eraser** 를 부른다. 예전에는 여기에 따로 구현한 삭제 로직이 있었는데,
고유키 색인을 남겨 두는 결함이 있었다. 같은 코드를 두 번 쓰면 한쪽만 고쳐진다.

그럼에도 이 도구가 따로 있는 이유는, 로그인·소유자 확인 없이 반복 테스트에서
빠르게 지우기 위해서다. 제품 경로는 소유자만 부를 수 있고 세션이 필요하다.

    python scripts/purge_workspace.py --workspace-id workspace-XXXX          # dry-run
    python scripts/purge_workspace.py --workspace-id workspace-XXXX --confirm

지우지 않는 것:

* `users` — 계정은 workspace 소유가 아니다
* Secret Manager 의 provider credential — 다른 workspace 가 같은 provider
  연결을 쓸 수 있다. 필요하면 `gcloud secrets delete` 로 따로 지운다
* Drive/GitHub 쪽 실제 파일 — 이 도구는 우리 저장소만 건드린다
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ip_risk_agent.gcp.operational_eraser import FirestoreOperationalEraser
from ip_risk_agent.gcp_contract import FIRESTORE_DATABASE, PROJECT_ID
from ip_risk_agent.persistence.core_firestore.eraser import FirestoreWorkspaceEraser


def _client(database: str):
    from google.cloud import firestore  # noqa: PLC0415 - 지연 import

    return firestore.AsyncClient(project=PROJECT_ID, database=database)


async def count_only(client, workspace_id: str) -> dict[str, int]:
    """무엇을 지울지 세기만 한다. 아무것도 바꾸지 않는다."""
    counts: dict[str, int] = {}
    recorded: list[tuple[str, str]] = []

    class _Recorder:
        def __init__(self, inner) -> None:
            self._inner = inner

        def collection(self, name: str):
            return _CollectionProxy(self._inner.collection(name), name)

    class _CollectionProxy:
        def __init__(self, inner, name: str) -> None:
            self._inner = inner
            self._name = name

        def document(self, document_id: str):
            return _DocumentProxy(self._inner.document(document_id), self._name)

        def where(self, **kwargs):
            return self._inner.where(**kwargs)

        def stream(self):
            return self._inner.stream()

    class _DocumentProxy:
        def __init__(self, inner, collection: str) -> None:
            self._inner = inner
            self._collection = collection

        async def get(self):
            return await self._inner.get()

        async def delete(self) -> None:
            recorded.append((self._collection, self._inner.id))

    recorder = _Recorder(client)
    for eraser in (
        FirestoreOperationalEraser(recorder),
        FirestoreWorkspaceEraser(recorder),
    ):
        await eraser.erase(workspace_id)
    for collection, _document_id in recorded:
        counts[collection] = counts.get(collection, 0) + 1
    return counts


async def purge(workspace_id: str, *, database: str, confirm: bool) -> dict[str, int]:
    client = _client(database)
    try:
        if not confirm:
            return await count_only(client, workspace_id)
        # 제품 경로와 같은 순서다 — operational 이 먼저여야 canonical 참조를
        # 살아 있을 때 읽을 수 있다.
        merged: dict[str, int] = {}
        for eraser in (
            FirestoreOperationalEraser(client),
            FirestoreWorkspaceEraser(client),
        ):
            for name, count in (await eraser.erase(workspace_id)).items():
                merged[name] = merged.get(name, 0) + count
        return merged
    finally:
        client.close()


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
