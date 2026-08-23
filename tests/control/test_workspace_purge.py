"""Workspace 삭제는 전체 말소다 (2026-08-22 결정).

soft delete 로 상태만 바꾸면 지웠다고 말한 데이터가 계속 남는다. 소유권 인계 기능이
없는 지금은 workspace 를 지운 사용자가 그 데이터에 다시 닿을 방법도 없으므로,
남겨 두는 것은 이득 없이 위험만 남긴다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts import AnalysisType, SourceType
from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.application.repositories.in_memory import InMemoryWorkspaceEraser
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.auth import User, UserStatus
from ip_risk_agent.core.common import ActorType, DomainInvariantError
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvidence,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


async def _seed(store: InMemoryControlStore, workspace_id: str, owner: str) -> None:
    async with store() as uow:
        if await uow.users.get(owner) is None:
            await uow.users.add(
                User(owner, f"{owner}@example.invalid", f"sub-{owner}", UserStatus.ACTIVE, NOW, NOW)
            )
        await uow.workspaces.add(
            RiskWorkspace(
                workspace_id, f"Workspace {workspace_id}", owner,
                "security-v1", "retention-v1", NOW, NOW,
            )
        )
        await uow.memberships.add(
            Membership(
                id=membership_id_for(workspace_id, owner),
                risk_workspace_id=workspace_id,
                user_id=owner,
                role=MembershipRole.OWNER,
                status=MembershipStatus.ACTIVE,
                invited_by=owner,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        artifact_id = f"artifact-{workspace_id}"
        await uow.artifacts.add(
            Artifact(
                artifact_id, workspace_id, f"mount-{workspace_id}",
                f"source-{workspace_id}", SourceType.GITHUB,
                "repo:path:src/main.py", "main.py", f"{workspace_id}/src/main.py",
                ArtifactStatus.ACTIVE, NOW, NOW,
            ),
            ArtifactState(artifact_id, "rev-1", "sha256:rev-1", ArtifactAvailability.AVAILABLE, NOW),
        )
        risk_id = f"risk-{workspace_id}"
        await uow.risks.add(
            Risk(
                risk_id, workspace_id, artifact_id, AnalysisType.PATENT,
                f"risk-patent:{workspace_id}", RiskLifecycleState.NEW,
                ReviewDisposition.UNREVIEWED,
                __import__("iprisk_contracts").ReviewPriority.HIGH,
                "summary", NOW, NOW, "job-1", NOW,
            )
        )
        await uow.risks.add_evidence(
            RiskEvidence(
                f"evidence-{workspace_id}", risk_id, "job-1", "evidence-1",
                "PATENT_CLAIM", "excerpt", "https://example.invalid/p/1", "rev-1", NOW,
            )
        )
        await uow.commit()


def _service(store: InMemoryControlStore) -> WorkspaceAdministrationService:
    counter = {"n": 0}

    def ids(prefix: str) -> str:
        counter["n"] += 1
        return f"{prefix}-{counter['n']}"

    return WorkspaceAdministrationService(
        unit_of_work_factory=store,
        clock=lambda: NOW + timedelta(minutes=1),
        id_factory=ids,
        workspace_erasers=(InMemoryWorkspaceEraser(store),),
    )


def test_deleting_a_workspace_erases_its_data() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        await _seed(store, "vws-1", "owner-1")
        await _service(store).request_workspace_deletion(
            risk_workspace_id="vws-1", actor_user_id="owner-1"
        )
        async with store() as uow:
            assert await uow.workspaces.get("vws-1") is None
            assert await uow.artifacts.get("artifact-vws-1") is None
            assert await uow.risks.get("risk-vws-1") is None
            assert await uow.risks.list_evidence("risk-vws-1") == ()
            assert await uow.memberships.get("vws-1", "owner-1") is None
            assert await uow.audit.list_for_workspace("vws-1") == ()
            # 계정은 workspace 소유가 아니다.
            assert await uow.users.get("owner-1") is not None

    run(scenario())


def test_deleting_one_workspace_leaves_the_other_untouched() -> None:
    """가장 위험한 실수는 범위를 넘어 지우는 것이다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        await _seed(store, "vws-1", "owner-1")
        await _seed(store, "vws-2", "owner-1")
        await _service(store).request_workspace_deletion(
            risk_workspace_id="vws-1", actor_user_id="owner-1"
        )
        async with store() as uow:
            assert await uow.workspaces.get("vws-2") is not None
            assert await uow.artifacts.get("artifact-vws-2") is not None
            assert await uow.risks.get("risk-vws-2") is not None
            assert len(await uow.risks.list_evidence("risk-vws-2")) == 1

    run(scenario())


def test_the_unique_key_index_is_released_so_the_identity_can_be_reused() -> None:
    """색인만 남으면 같은 이름·같은 키를 다시 쓸 수 없다.

    지운 뒤에도 재사용이 막히면 사용자에게는 "지워지지 않은 것" 과 구별되지 않는다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        await _seed(store, "vws-1", "owner-1")
        await _service(store).request_workspace_deletion(
            risk_workspace_id="vws-1", actor_user_id="owner-1"
        )
        async with store() as uow:
            assert await uow.risks.get_by_key("risk-patent:vws-1") is None
        # 같은 식별자로 다시 만들 수 있어야 한다.
        await _seed(store, "vws-1", "owner-1")
        async with store() as uow:
            assert await uow.workspaces.get("vws-1") is not None

    run(scenario())


def test_only_the_owner_may_delete_and_data_survives_a_refusal() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        await _seed(store, "vws-1", "owner-1")
        async with store() as uow:
            await uow.users.add(
                User("member-1", "m@example.invalid", "sub-member", UserStatus.ACTIVE, NOW, NOW)
            )
            await uow.memberships.add(
                Membership(
                    id=membership_id_for("vws-1", "member-1"),
                    risk_workspace_id="vws-1",
                    user_id="member-1",
                    role=MembershipRole.VIEWER,
                    status=MembershipStatus.ACTIVE,
                    invited_by="owner-1",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await uow.commit()
        with pytest.raises(Exception):
            await _service(store).request_workspace_deletion(
                risk_workspace_id="vws-1", actor_user_id="member-1"
            )
        async with store() as uow:
            assert await uow.workspaces.get("vws-1") is not None
            assert await uow.risks.get("risk-vws-1") is not None

    run(scenario())


def test_erasing_twice_is_safe() -> None:
    """지우다 실패하면 다시 부른다. 두 번째 호출이 터지면 복구할 길이 없다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        await _seed(store, "vws-1", "owner-1")
        eraser = InMemoryWorkspaceEraser(store)
        first = await eraser.erase("vws-1")
        second = await eraser.erase("vws-1")
        assert first, "첫 호출은 무언가를 지워야 한다"
        assert second == {}

    run(scenario())


def test_a_deletion_stuck_at_deleting_finishes_on_retry() -> None:
    """DELETING 에 갇힌 workspace 는 삭제를 다시 부르면 이어서 마무리된다.

    eraser 가 빠졌거나 지우다 실패하면 workspace 는 DELETING 으로 남는다.
    "ACTIVE 만 지울 수 있다" 는 규칙이 그 재시도를 막고 있었다 — 프로덕션에서
    workspace 네 개가 그 상태로 영영 지워지지 않았다.
    """

    async def scenario() -> None:
        store = InMemoryControlStore()
        await _seed(store, "vws-1", "owner-1")
        # eraser 없이 지우면 표시만 바뀐다 — 고착 상태를 그대로 만든다.
        stuck = WorkspaceAdministrationService(
            unit_of_work_factory=store,
            clock=lambda: NOW + timedelta(minutes=1),
            id_factory=lambda prefix: f"{prefix}-stuck",
            workspace_erasers=(),
        )
        await stuck.request_workspace_deletion(
            risk_workspace_id="vws-1", actor_user_id="owner-1"
        )
        async with store() as uow:
            workspace = await uow.workspaces.get("vws-1")
            assert workspace is not None
            assert workspace.status.value == "DELETING"

        # 재시도 — eraser 가 있으면 이어서 끝까지 지운다.
        await _service(store).request_workspace_deletion(
            risk_workspace_id="vws-1", actor_user_id="owner-1"
        )
        async with store() as uow:
            assert await uow.workspaces.get("vws-1") is None

    run(scenario())
