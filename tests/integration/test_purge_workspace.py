"""테스트용 workspace purge 도구의 안전장치.

제품 삭제도 전체 말소이고 같은 eraser 를 쓴다. 이 도구는 로그인 없이 반복
테스트에서 지우기 위한 것이다. 가장 큰 위험은 잘못된 database 를 지우는 것이다 — v1 운영 DB 가 같은 project 안에 `(default)` 로 있고, Firestore
도구는 대부분 그것을 기본값으로 쓴다.

Firestore 에 접속하지 않는다. 검증 규칙과 삭제 순서만 확인한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ip_risk_agent.gcp_contract import FIRESTORE_DATABASE
from scripts.purge_workspace import validate_target

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "purge_workspace.py"


@pytest.mark.parametrize("database", ("(default)", "", "ip-risk-agent", "some-other-db"))
def test_refuses_any_database_other_than_the_v2_one(database: str) -> None:
    problem = validate_target("workspace-abc", database)
    assert problem is not None
    assert "refusing to touch database" in problem


@pytest.mark.parametrize(
    "workspace_id",
    (
        "workspace-mount:v1:abc",  # canonical 자식 id 는 접두사를 공유한다
        "artifact:v1:abc",
        "",
        "mount-1",
    ),
)
def test_refuses_anything_that_is_not_a_workspace_id(workspace_id: str) -> None:
    assert validate_target(workspace_id, FIRESTORE_DATABASE) is not None


def test_accepts_a_real_workspace_id_on_the_v2_database() -> None:
    assert validate_target("workspace-n8OH8zSgcMxIwZ8XIKWcM3585T6ShkyX", FIRESTORE_DATABASE) is None


class _FakeDocument:
    def __init__(self, collection: str, document_id: str, data: dict, log: list) -> None:
        self._collection = collection
        self.id = document_id
        self._data = data
        self._log = log

    @property
    def exists(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return dict(self._data)

    async def get(self):
        return self

    async def delete(self) -> None:
        self._log.append((self._collection, self.id))


class _FakeCollection:
    def __init__(self, name: str, documents: dict, log: list, predicate=None) -> None:
        self._name = name
        self._documents = documents
        self._log = log
        self._predicate = predicate

    def document(self, document_id: str) -> _FakeDocument:
        return _FakeDocument(
            self._name, document_id, self._documents.get(document_id, {}), self._log
        )

    def where(self, *, filter) -> _FakeCollection:
        """실제 필터를 흉내낸다.

        필터를 무시하면 시험이 프로덕션보다 넓게 지우는 것을 보고, 있지도 않은
        결함을 쫓게 된다. 실제로 그렇게 한 번 헛짚었다.
        """
        field = filter.field_path
        expected = filter.value
        return _FakeCollection(
            self._name,
            self._documents,
            self._log,
            lambda data: data.get(field) == expected,
        )

    async def _iterate(self):
        for document_id, data in list(self._documents.items()):
            if (self._name, document_id) in self._log:
                continue
            if self._predicate is not None and not self._predicate(data):
                continue
            yield _FakeDocument(self._name, document_id, data, self._log)

    def stream(self):
        return self._iterate()


class _FakeClient:
    """지운 순서를 기록하는 최소한의 Firestore 대역."""

    def __init__(self, collections: dict[str, dict]) -> None:
        self._collections = collections
        self.deleted: list[tuple[str, str]] = []

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(name, self._collections.get(name, {}), self.deleted)

    def close(self) -> None:
        return None


def _sample() -> dict[str, dict]:
    return {
        "workspace_mounts": {
            "mount-1": {
                "risk_workspace_id": "workspace-abc",
                "source_workspace_id": "source-1",
                "source_connection_id": "conn-1",
            }
        },
        "artifacts": {"artifact-1": {"risk_workspace_id": "workspace-abc"}},
        "artifact_states": {"artifact-1": {}},
        "risks": {
            "risk-1": {"risk_workspace_id": "workspace-abc"},
            "unique-risk-key:v1:x": {
                "record_kind": "unique_key",
                "owner_document_id": "risk-1",
            },
        },
        "risk_workspaces": {"workspace-abc": {}},
    }


def test_deletion_only_happens_behind_the_confirm_flag(monkeypatch) -> None:
    """기본은 dry-run 이다. 실수로 실행해도 아무것도 바뀌지 않아야 한다."""
    import asyncio

    from scripts import purge_workspace

    client = _FakeClient(_sample())
    monkeypatch.setattr(purge_workspace, "_client", lambda database: client)
    counts = asyncio.run(
        purge_workspace.purge(
            "workspace-abc", database=FIRESTORE_DATABASE, confirm=False
        )
    )
    assert client.deleted == [], "dry-run 은 아무것도 지우지 않아야 한다"
    assert sum(counts.values()) > 0, "무엇을 지울지는 세어 보여야 한다"


def test_workspace_document_is_deleted_last(monkeypatch) -> None:
    """중간에 실패하면 workspace 가 남아 다시 시도할 수 있어야 한다.

    workspace 를 먼저 지우면 남은 레코드를 찾을 실마리가 사라진다.
    """
    import asyncio

    from scripts import purge_workspace

    client = _FakeClient(_sample())
    monkeypatch.setattr(purge_workspace, "_client", lambda database: client)
    asyncio.run(
        purge_workspace.purge(
            "workspace-abc", database=FIRESTORE_DATABASE, confirm=True
        )
    )
    assert client.deleted, "confirm 이면 실제로 지워야 한다"
    assert client.deleted[-1] == ("risk_workspaces", "workspace-abc")


def test_the_unique_key_index_is_erased_with_its_owner(monkeypatch) -> None:
    """색인만 남으면 같은 식별자를 다시 쓸 수 없다.

    예전 구현이 이것을 빠뜨려 실제 데이터에 고아 색인이 쌓였다.
    """
    import asyncio

    from scripts import purge_workspace

    client = _FakeClient(_sample())
    monkeypatch.setattr(purge_workspace, "_client", lambda database: client)
    asyncio.run(
        purge_workspace.purge(
            "workspace-abc", database=FIRESTORE_DATABASE, confirm=True
        )
    )
    assert ("risks", "unique-risk-key:v1:x") in client.deleted


def _shared_connection_sample() -> dict[str, dict]:
    """두 workspace 가 같은 Drive 계정 연결을 공유하는 상태."""
    return {
        "workspace_mounts": {
            "mount-ours": {
                "risk_workspace_id": "workspace-abc",
                "source_workspace_id": "source-1",
                "source_connection_id": "conn-shared",
            },
            "mount-theirs": {
                "risk_workspace_id": "workspace-other",
                "source_workspace_id": "source-1",
                "source_connection_id": "conn-shared",
            },
        },
        "source_operational_drive_runtime": {
            # 계정 단위 연결의 감시 채널과 변경 커서. 이것이 사라지면 남은
            # workspace 의 변경 감지가 조용히 끊긴다.
            "conn-shared": {"record": {"connection_id": "conn-shared"}},
        },
        "source_operational_drive_tracking": {
            "mount-ours": {"record": {"mount_id": "mount-ours"}},
            "mount-theirs": {"record": {"mount_id": "mount-theirs"}},
        },
        "risk_workspaces": {"workspace-abc": {}, "workspace-other": {}},
    }


def test_a_connection_shared_with_another_workspace_is_kept(monkeypatch) -> None:
    """connection 은 workspace 소유가 아니다.

    Drive 연결은 계정 단위라 여러 workspace 의 mount 가 같은 것을 공유한다.
    connection 으로 걸린 operational 기록을 함께 지우면, workspace 하나를 지웠는데
    다른 workspace 의 감시가 끊긴다.
    """
    import asyncio

    from scripts import purge_workspace

    client = _FakeClient(_shared_connection_sample())
    monkeypatch.setattr(purge_workspace, "_client", lambda database: client)
    asyncio.run(
        purge_workspace.purge(
            "workspace-abc", database=FIRESTORE_DATABASE, confirm=True
        )
    )
    deleted = set(client.deleted)
    assert ("source_operational_drive_tracking", "mount-ours") in deleted
    assert ("source_operational_drive_tracking", "mount-theirs") not in deleted
    assert ("source_operational_drive_runtime", "conn-shared") not in deleted
    assert ("workspace_mounts", "mount-theirs") not in deleted
    assert ("risk_workspaces", "workspace-other") not in deleted


def test_a_connection_no_other_workspace_uses_is_erased(monkeypatch) -> None:
    """마지막 workspace 를 지우면 그 연결의 런타임도 남길 이유가 없다."""
    import asyncio

    from scripts import purge_workspace

    sample = _shared_connection_sample()
    del sample["workspace_mounts"]["mount-theirs"]
    del sample["source_operational_drive_tracking"]["mount-theirs"]
    client = _FakeClient(sample)
    monkeypatch.setattr(purge_workspace, "_client", lambda database: client)
    asyncio.run(
        purge_workspace.purge(
            "workspace-abc", database=FIRESTORE_DATABASE, confirm=True
        )
    )
    assert ("source_operational_drive_runtime", "conn-shared") in set(client.deleted)
