from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from ip_risk_agent.application.repositories import (
    InMemoryControlStore,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.core.audit import AuditEvent, AuditEventType
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.mounts import MountStatus, WorkspaceMount
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 13, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def __call__(self, kind: str) -> str:
        self._next += 1
        return f"{kind}-{self._next}"


def make_service(store: InMemoryControlStore) -> WorkspaceAdministrationService:
    return WorkspaceAdministrationService(
        unit_of_work_factory=store,
        clock=lambda: NOW,
        id_factory=SequentialIds(),
    )


def make_user(user_id: str, email: str | None = None) -> User:
    return User(
        id=user_id,
        google_subject=f"subject-{user_id}",
        email=email or f"{user_id}@example.com",
        display_name=user_id,
        created_at=NOW,
        last_login_at=NOW,
    )


def make_membership(user_id: str, role: MembershipRole) -> Membership:
    return Membership(
        id=membership_id_for("vws-1", user_id),
        risk_workspace_id="vws-1",
        user_id=user_id,
        role=role,
        status=MembershipStatus.ACTIVE,
        invited_by="owner-1",
        created_at=NOW,
        updated_at=NOW,
    )


def make_workspace() -> RiskWorkspace:
    return RiskWorkspace(
        id="vws-1",
        name="Workspace",
        owner_user_id="owner-1",
        security_policy_version="security-v1",
        retention_policy_version="retention-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def make_mount(mount_id: str, status: MountStatus) -> WorkspaceMount:
    return WorkspaceMount(
        id=mount_id,
        risk_workspace_id="vws-1",
        source_workspace_id=f"source-{mount_id}",
        alias=mount_id,
        mounted_by_user_id="manager-1",
        source_connection_id=f"connection-{mount_id}",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def test_workspace_invitation_and_acceptance_are_committed_atomically() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        service = make_service(store)
        async with store() as uow:
            await uow.users.add(make_user("owner-1"))
            await uow.users.add(make_user("reviewer-1", "reviewer@example.com"))
            await uow.commit()

        creation = await service.create_workspace(
            owner_user_id="owner-1",
            name="Project Aurora",
            security_policy_version="security-v1",
            retention_policy_version="retention-v1",
        )
        invitation = await service.invite_member(
            risk_workspace_id=creation.workspace.id,
            actor_user_id="owner-1",
            email="Reviewer@Example.com",
            role=MembershipRole.RISK_REVIEWER,
        )
        acceptance = await service.accept_invitation(
            invitation_id=invitation.invitation.id,
            authenticated_user_id="reviewer-1",
            verified_email="reviewer@example.com",
        )

        async with store() as uow:
            assert await uow.workspaces.get(creation.workspace.id) == creation.workspace
            assert await uow.memberships.get(
                creation.workspace.id, "owner-1"
            ) == creation.owner_membership
            assert (
                await uow.memberships.get_invitation(invitation.invitation.id)
            ).status is InvitationStatus.ACCEPTED
            assert await uow.memberships.get(
                creation.workspace.id, "reviewer-1"
            ) == acceptance.membership
            assert len(await uow.audit.list_for_workspace(creation.workspace.id)) == 3

    run(scenario())


def test_failure_after_aggregate_writes_rolls_back_entire_workspace_creation() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        existing_audit = AuditEvent(
            id="audit-existing",
            risk_workspace_id="seed-vws",
            event_type=AuditEventType.WORKSPACE_CREATED,
            actor_type=ActorType.USER,
            actor_user_id="owner-1",
            occurred_at=NOW,
        )
        async with store() as uow:
            await uow.users.add(make_user("owner-1"))
            await uow.audit.append(existing_audit)
            await uow.commit()

        ids = {"workspace": "vws-failed", "audit": "audit-existing"}
        service = WorkspaceAdministrationService(
            unit_of_work_factory=store,
            clock=lambda: NOW,
            id_factory=ids.__getitem__,
        )
        with pytest.raises(UniqueConstraintViolation, match="audit event"):
            await service.create_workspace(
                owner_user_id="owner-1",
                name="Must Roll Back",
                security_policy_version="security-v1",
                retention_policy_version="retention-v1",
            )

        async with store() as uow:
            assert await uow.workspaces.get("vws-failed") is None
            assert await uow.memberships.get("vws-failed", "owner-1") is None
            assert await uow.audit.list_for_workspace("seed-vws") == (existing_audit,)

    run(scenario())


def test_source_manager_demotion_loads_all_owned_mounts_in_same_transaction() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        service = make_service(store)
        active_mount = make_mount("active", MountStatus.ACTIVE)
        disabled_mount = make_mount("disabled", MountStatus.DISABLED)
        async with store() as uow:
            await uow.workspaces.add(make_workspace())
            await uow.memberships.add(make_membership("owner-1", MembershipRole.OWNER))
            await uow.memberships.add(
                make_membership("manager-1", MembershipRole.SOURCE_MANAGER)
            )
            await uow.mounts.add(active_mount)
            await uow.mounts.add(disabled_mount)
            await uow.commit()

        plan = await service.change_member_role(
            risk_workspace_id="vws-1",
            actor_user_id="owner-1",
            target_user_id="manager-1",
            new_role=MembershipRole.RISK_REVIEWER,
        )

        assert tuple(mount.id for mount in plan.mounts) == ("active",)
        async with store() as uow:
            membership = await uow.memberships.get("vws-1", "manager-1")
            assert membership is not None
            assert membership.role is MembershipRole.RISK_REVIEWER
            assert (await uow.mounts.get("active")).status is MountStatus.MANAGER_ACTION_REQUIRED
            assert (await uow.mounts.get("disabled")).status is MountStatus.DISABLED
            notifications = await uow.notifications.list_for_user("owner-1")
            assert len(notifications) == 1
            assert notifications[0].metadata_safe["mount_ids"] == ("active",)
            assert len(await uow.audit.list_for_workspace("vws-1")) == 1

    run(scenario())


def test_ownership_transfer_then_member_removal_preserves_mount_for_new_owner_action() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        service = make_service(store)
        owner_mount = WorkspaceMount(
            id="owner-mount",
            risk_workspace_id="vws-1",
            source_workspace_id="source-owner",
            alias="owner-source",
            mounted_by_user_id="owner-1",
            source_connection_id="connection-owner",
            status=MountStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        async with store() as uow:
            await uow.workspaces.add(make_workspace())
            await uow.memberships.add(make_membership("owner-1", MembershipRole.OWNER))
            await uow.memberships.add(
                make_membership("reviewer-1", MembershipRole.RISK_REVIEWER)
            )
            await uow.mounts.add(owner_mount)
            await uow.commit()

        transfer = await service.transfer_ownership(
            risk_workspace_id="vws-1",
            actor_user_id="owner-1",
            new_owner_user_id="reviewer-1",
        )
        assert transfer.workspace.owner_user_id == "reviewer-1"
        assert transfer.previous_owner_membership.role is MembershipRole.SOURCE_MANAGER
        assert transfer.new_owner_membership.role is MembershipRole.OWNER

        removal = await service.remove_member(
            risk_workspace_id="vws-1",
            actor_user_id="reviewer-1",
            target_user_id="owner-1",
        )
        assert removal.membership.status is MembershipStatus.REMOVED
        async with store() as uow:
            workspace = await uow.workspaces.get("vws-1")
            previous_owner = await uow.memberships.get("vws-1", "owner-1")
            new_owner = await uow.memberships.get("vws-1", "reviewer-1")
            assert workspace is not None and workspace.owner_user_id == "reviewer-1"
            assert previous_owner is not None and previous_owner.status is MembershipStatus.REMOVED
            assert new_owner is not None and new_owner.role is MembershipRole.OWNER
            assert (
                await uow.mounts.get("owner-mount")
            ).status is MountStatus.MANAGER_ACTION_REQUIRED
            assert len(await uow.notifications.list_for_user("reviewer-1")) == 1
            assert len(await uow.audit.list_for_workspace("vws-1")) == 2

    run(scenario())


def test_mount_alias_collision_rolls_back_audit_and_mount_mutation() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        service = make_service(store)
        first = WorkspaceMount(
            id="backend",
            risk_workspace_id="vws-1",
            source_workspace_id="source-backend",
            alias="Backend",
            mounted_by_user_id="owner-1",
            source_connection_id="connection-backend",
            status=MountStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        second = WorkspaceMount(
            id="frontend",
            risk_workspace_id="vws-1",
            source_workspace_id="source-frontend",
            alias="Frontend",
            mounted_by_user_id="owner-1",
            source_connection_id="connection-frontend",
            status=MountStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
        )
        async with store() as uow:
            await uow.workspaces.add(make_workspace())
            await uow.memberships.add(make_membership("owner-1", MembershipRole.OWNER))
            await uow.mounts.add(first)
            await uow.mounts.add(second)
            await uow.commit()

        with pytest.raises(UniqueConstraintViolation, match="alias"):
            await service.rename_mount(
                risk_workspace_id="vws-1",
                actor_user_id="owner-1",
                mount_id="frontend",
                new_alias="backend",
            )

        async with store() as uow:
            assert (await uow.mounts.get("frontend")).alias == "Frontend"
            assert await uow.audit.list_for_workspace("vws-1") == ()

    run(scenario())
