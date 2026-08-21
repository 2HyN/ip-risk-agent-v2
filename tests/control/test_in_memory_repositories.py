from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from iprisk_contracts import (
    AnalysisType,
    ChangeType,
    ReviewPriority,
    SourceArtifactRef,
    SourceChange,
    SourceType,
)
from ip_risk_agent.application.process_change import ChangeEvent, ChangeEventStatus
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    InMemoryControlStore,
    TransactionClosedError,
    UniqueConstraintViolation,
)
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.memberships import (
    InvitationStatus,
    Membership,
    MembershipInvitation,
    MembershipRole,
    MembershipStatus,
    invitation_id_for,
    membership_id_for,
)
from ip_risk_agent.core.mounts import MountStatus, WorkspaceMount
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


def make_user(user_id: str, subject: str | None = None) -> User:
    return User(
        id=user_id,
        google_subject=subject or f"subject-{user_id}",
        email=f"{user_id}@example.com",
        display_name=user_id,
        created_at=NOW,
        last_login_at=NOW,
    )


def make_workspace(workspace_id: str = "vws-1") -> RiskWorkspace:
    return RiskWorkspace(
        id=workspace_id,
        name="Workspace",
        owner_user_id="owner-1",
        security_policy_version="security-v1",
        retention_policy_version="retention-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def make_membership(user_id: str, role: MembershipRole = MembershipRole.VIEWER) -> Membership:
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


def make_mount(
    mount_id: str,
    alias: str,
    source_workspace_id: str,
) -> WorkspaceMount:
    return WorkspaceMount(
        id=mount_id,
        risk_workspace_id="vws-1",
        source_workspace_id=source_workspace_id,
        alias=alias,
        mounted_by_user_id="owner-1",
        source_connection_id=f"connection-{mount_id}",
        status=MountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def make_artifact(artifact_id: str, source_artifact_id: str) -> tuple[Artifact, ArtifactState]:
    artifact = Artifact(
        id=artifact_id,
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        source_workspace_id="source-1",
        source_type=SourceType.GITHUB,
        source_artifact_id=source_artifact_id,
        display_name="main.py",
        logical_path="backend/main.py",
        status=ArtifactStatus.ACTIVE,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    return artifact, ArtifactState(
        artifact_id=artifact.id,
        latest_revision="revision-1",
        latest_checksum="checksum-1",
        availability_state=ArtifactAvailability.AVAILABLE,
        updated_at=NOW,
    )


def make_change(event_id: str, fingerprint: str) -> ChangeEvent:
    return ChangeEvent(
        id=event_id,
        event_fingerprint=fingerprint,
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        source_workspace_id="source-1",
        source_artifact_id="path:main.py",
        source_type=SourceType.GITHUB,
        change_type=ChangeType.UPDATE,
        revision="revision-1",
        previous_revision=None,
        observed_at=NOW,
        status=ChangeEventStatus.PENDING,
        attempts=0,
        created_at=NOW,
        updated_at=NOW,
        source_change=SourceChange(
            contract_version="1",
            event_id=event_id,
            event_fingerprint=fingerprint,
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            source_workspace_id="source-1",
            source_type=SourceType.GITHUB,
            artifact=SourceArtifactRef(
                source_artifact_id="path:main.py",
                display_name="main.py",
            ),
            change_type=ChangeType.UPDATE,
            revision="revision-1",
            observed_at=NOW,
            safe_metadata={},
        ),
    )


def make_risk(risk_id: str, risk_key: str) -> Risk:
    return Risk(
        id=risk_id,
        risk_workspace_id="vws-1",
        artifact_id="artifact-1",
        analysis_type=AnalysisType.PATENT,
        risk_key=risk_key,
        lifecycle_state=RiskLifecycleState.NEW,
        review_disposition=ReviewDisposition.UNREVIEWED,
        review_priority=ReviewPriority.HIGH,
        summary="Potential overlap",
        first_seen_at=NOW,
        last_seen_at=NOW,
        latest_analysis_job_id="job-1",
        updated_at=NOW,
    )


def test_commit_publishes_snapshot_and_implicit_exit_rolls_back() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        async with store() as uow:
            await uow.users.add(make_user("user-1"))

        async with store() as uow:
            assert await uow.users.get("user-1") is None
            await uow.users.add(make_user("user-1"))
            await uow.commit()

        async with store() as uow:
            assert await uow.users.get("user-1") == make_user("user-1")
            await uow.rollback()

        with pytest.raises(TransactionClosedError):
            await uow.users.get("user-1")

    run(scenario())


def test_concurrent_snapshots_reject_lost_update() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        first = await store().__aenter__()
        second = await store().__aenter__()
        await first.users.add(make_user("user-1"))
        await second.users.add(make_user("user-2"))
        await first.commit()
        with pytest.raises(ConcurrencyConflictError):
            await second.commit()
        await second.rollback()
        async with store() as verification:
            assert await verification.users.get("user-1") is not None
            assert await verification.users.get("user-2") is None

    run(scenario())


def test_user_and_membership_storage_enforce_canonical_identity() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        invitation = MembershipInvitation(
            id=invitation_id_for("vws-1", "viewer@example.com"),
            risk_workspace_id="vws-1",
            email="viewer@example.com",
            role=MembershipRole.VIEWER,
            status=InvitationStatus.PENDING,
            invited_by="owner-1",
            created_at=NOW,
            updated_at=NOW,
        )
        async with store() as uow:
            await uow.users.add(make_user("user-1", "shared-subject"))
            with pytest.raises(UniqueConstraintViolation, match="Google subject"):
                await uow.users.add(make_user("user-2", "shared-subject"))
            workspace = make_workspace()
            await uow.workspaces.add(workspace)
            await uow.memberships.add(make_membership("user-1"))
            await uow.memberships.add_invitation(invitation)
            assert len(await uow.memberships.list_members("vws-1")) == 1
            assert await uow.memberships.list_invitations("vws-1") == (invitation,)
            assert await uow.workspaces.list_for_user("user-1") == (workspace,)
            with pytest.raises(UniqueConstraintViolation, match="membership record"):
                await uow.memberships.add(make_membership("user-1"))

    run(scenario())


def test_mount_alias_and_source_workspace_uniqueness_are_transactional() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        async with store() as uow:
            await uow.mounts.add(make_mount("mount-1", "Backend", "source-1"))
            with pytest.raises(UniqueConstraintViolation, match="alias"):
                await uow.mounts.add(make_mount("mount-2", "backend", "source-2"))
            with pytest.raises(UniqueConstraintViolation, match="source workspace"):
                await uow.mounts.add(make_mount("mount-3", "docs", "source-1"))
            await uow.rollback()

    run(scenario())


def test_artifact_change_event_and_risk_unique_keys_are_enforced() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        first_artifact, first_state = make_artifact("artifact-1", "path:main.py")
        duplicate_artifact, duplicate_state = make_artifact("artifact-2", "path:main.py")
        async with store() as uow:
            await uow.artifacts.add(first_artifact, first_state)
            assert await uow.artifacts.list_for_workspace("vws-1") == (
                first_artifact,
            )
            assert await uow.artifacts.list_for_workspace("other-vws") == ()
            with pytest.raises(UniqueConstraintViolation, match="source artifact identity"):
                await uow.artifacts.add(duplicate_artifact, duplicate_state)
            await uow.change_events.add(make_change("change-1", "fingerprint-1"))
            with pytest.raises(UniqueConstraintViolation, match="fingerprint"):
                await uow.change_events.add(make_change("change-2", "fingerprint-1"))
            await uow.risks.add(make_risk("risk-1", "risk-key-1"))
            with pytest.raises(UniqueConstraintViolation, match="risk key"):
                await uow.risks.add(make_risk("risk-2", "risk-key-1"))

    run(scenario())


def test_append_only_event_repositories_expose_no_update_or_delete_api() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        async with store() as uow:
            assert not hasattr(uow.audit, "save")
            assert not hasattr(uow.audit, "remove")
            assert not hasattr(uow.risks, "save_event")
            assert not hasattr(uow.risks, "remove_event")
            risk = make_risk("risk-1", "risk-key-1")
            await uow.risks.add(risk)
            await uow.risks.append_event(
                RiskEvent(
                    id="risk-event-1",
                    risk_id=risk.id,
                    event_type=RiskEventType.DETECTED,
                    actor_type=ActorType.SYSTEM,
                    occurred_at=NOW,
                )
            )
            with pytest.raises(UniqueConstraintViolation, match="risk event"):
                await uow.risks.append_event(
                    RiskEvent(
                        id="risk-event-1",
                        risk_id=risk.id,
                        event_type=RiskEventType.DETECTED,
                        actor_type=ActorType.SYSTEM,
                        occurred_at=NOW,
                    )
                )

    run(scenario())
