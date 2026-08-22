"""가리키는 기록이 없는 Source 자격증명 Secret 을 지운다.

## 왜 필요한가

Workspace 삭제는 전체 말소인데, 예전 eraser 는 Secret Manager 의 provider
자격증명을 남겼다. 그 결과 workspace 를 전부 지운 뒤에도 Drive refresh token 을
담은 Secret 이 남았고, **그것을 가리키던 pending connection 기록이 함께 사라진
뒤라 아무도 다시 찾아 지울 수 없었다.**

지금은 eraser 가 함께 지운다(``gcp/operational_eraser.py``). 이 도구는 그 수정
이전에 이미 남아 버린 것들을 정리한다. 앞으로도 삭제가 중간에 실패해 Secret 만
남는 경우가 있을 수 있으므로 도구는 남겨 둔다.

## 무엇을 고아로 보는가

`iprisk-v2-cred-` 로 시작하는 Secret 중에서, Firestore 의 어떤 pending connection
도 ``credential_ref.key_id`` 로 가리키지 않는 것. 접두사 조건이 v1 자격증명
(``ipra-*``)과 배포용 고정 Secret 을 처음부터 배제한다.

비교는 전체 경로가 아니라 **이름의 마지막 조각**으로 한다. Secret Manager 는
목록을 ``projects/<번호>/...`` 로 돌려주는데 저장된 참조는 ``projects/<ID>/...``
라 전체 경로로 맞추면 하나도 걸리지 않는다 — 그러면 "고아 0 개" 라는 틀린 답이
나오고, 남은 자격증명은 그대로 남는다.

## 쓰는 법

    python scripts/purge_orphan_credentials.py            # dry-run
    python scripts/purge_orphan_credentials.py --confirm

Secret 값은 읽지도 출력하지도 않는다. 이름만 다룬다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ip_risk_agent.gcp_contract import (
    DYNAMIC_CREDENTIAL_SECRET_PREFIX,
    FIRESTORE_DATABASE,
    PROJECT_ID,
)

PENDING_CONNECTIONS = "source_operational_pending_connections"


async def referenced_key_ids(database: str) -> set[str]:
    """살아 있는 연결이 가리키는 Secret 이름을 모은다.

    하나라도 못 읽으면 지우지 않는 편이 안전하므로 예외는 올린다. 목록이 비어
    보이는 것과 실제로 비어 있는 것은 결과가 정반대다.
    """
    from google.cloud import firestore  # noqa: PLC0415 - 지연 import

    client = firestore.AsyncClient(project=PROJECT_ID, database=database)
    try:
        found: set[str] = set()
        async for document in client.collection(PENDING_CONNECTIONS).stream():
            data = document.to_dict() or {}
            for holder in (data, data.get("record") or {}):
                if not isinstance(holder, dict):
                    continue
                ref = holder.get("credential_ref")
                if isinstance(ref, dict) and ref.get("key_id"):
                    found.add(str(ref["key_id"]))
        return found
    finally:
        client.close()


def credential_secret_names() -> list[str]:
    """v2 Source 자격증명 Secret 의 이름.

    목록은 ``projects/<번호>/...`` 로 오는데, 그대로 두면 project 부분이 우리
    것인지 이름만 보고 확인할 수 없다. 그래서 project ID 형태로 맞춰 돌려준다.
    두 형태 모두 삭제 API 가 받는다.
    """
    from google.cloud import secretmanager  # noqa: PLC0415 - 지연 import

    client = secretmanager.SecretManagerServiceClient()
    try:
        return sorted(
            f"projects/{PROJECT_ID}/secrets/{secret_id(secret.name)}"
            for secret in client.list_secrets(parent=f"projects/{PROJECT_ID}")
            if secret_id(secret.name).startswith(DYNAMIC_CREDENTIAL_SECRET_PREFIX + "-")
        )
    finally:
        client.transport.close()


def secret_id(name: str) -> str:
    """전체 이름에서 Secret 이름만 뗀다.

    project 부분은 번호일 수도 ID 일 수도 있어 비교에 쓸 수 없다.
    """
    return name.rsplit("/", 1)[-1]


def delete_secret(name: str) -> None:
    """접두사를 한 번 더 확인하고 지운다.

    이 도구의 유일한 파괴적 동작이다. 호출부의 필터를 믿지 않고 여기서 다시
    확인한다 — v1 자격증명과 배포용 고정 Secret 이 같은 project 에 있다.
    """
    from google.cloud import secretmanager  # noqa: PLC0415 - 지연 import

    prefix = f"projects/{PROJECT_ID}/secrets/{DYNAMIC_CREDENTIAL_SECRET_PREFIX}-"
    if not name.startswith(prefix):
        raise ValueError("refusing to delete a secret outside the v2 credential prefix")
    client = secretmanager.SecretManagerServiceClient()
    try:
        client.delete_secret(name=name)
    finally:
        client.transport.close()


def orphans(names: list[str], referenced: set[str]) -> list[str]:
    live = {secret_id(name) for name in referenced}
    return [name for name in names if secret_id(name) not in live]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=FIRESTORE_DATABASE)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="실제로 지운다. 없으면 셀 뿐이고 아무것도 바꾸지 않는다.",
    )
    args = parser.parse_args()

    if args.database != FIRESTORE_DATABASE:
        print(f"STOP: refusing to read database {args.database!r}", file=sys.stderr)
        return 2

    referenced = asyncio.run(referenced_key_ids(args.database))
    names = credential_secret_names()
    stray = orphans(names, referenced)

    print(f"v2 source credentials      {len(names)}")
    print(f"still referenced           {len(names) - len(stray)}")
    print(f"orphaned                   {len(stray)}")
    for name in stray:
        print(f"  {secret_id(name)}")

    if not stray:
        return 0
    if not args.confirm:
        print("re-run with --confirm to delete")
        return 0
    for name in stray:
        delete_secret(name)
    print(f"deleted: {len(stray)} secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
