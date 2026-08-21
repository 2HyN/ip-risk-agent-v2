"""테스트용 workspace purge 도구의 안전장치.

제품 삭제 정책이 정해지기 전의 임시 도구다. 가장 큰 위험은 잘못된 database 를
지우는 것이다 — v1 운영 DB 가 같은 project 안에 `(default)` 로 있고, Firestore
도구는 대부분 그것을 기본값으로 쓴다.

Firestore 에 접속하지 않고 검증 규칙만 확인한다.
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


def test_deletion_only_happens_behind_the_confirm_flag() -> None:
    """기본은 dry-run 이다. 실수로 실행해도 아무것도 바뀌지 않아야 한다."""
    source = SCRIPT.read_text(encoding="utf-8")
    guard = source.index("    if confirm:")
    delete_call = source.index("await client.collection(collection).document")
    assert guard < delete_call


def test_workspace_document_is_deleted_last() -> None:
    """중간에 실패하면 workspace 가 남아 다시 시도할 수 있어야 한다.

    workspace 를 먼저 지우면 남은 레코드를 찾을 실마리가 사라진다.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index('"risk_workspaces"') > source.index('counts["artifact_states"]')


def test_users_are_never_purged() -> None:
    """계정은 workspace 소유가 아니다. 다른 workspace 의 멤버일 수 있다."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]
    assert '"users"' not in body
