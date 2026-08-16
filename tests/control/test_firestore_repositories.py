from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from iprisk_contracts import AnalysisType, ChangeType, ReviewPriority, SourceType
from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.process_change import ChangeEvent, ChangeEventStatus
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    InMemoryControlStore,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.core.audit import AuditEvent, AuditEventType
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.artifacts import (
    Artifact,
    ArtifactAvailability,
    ArtifactState,
    ArtifactStatus,
)
from ip_risk_agent.core.memberships import (
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
)
from ip_risk_agent.core.mounts import MountStatus, WorkspaceMount
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskEvidence,
    RiskLifecycleState,
)
from ip_risk_agent.persistence.core_firestore.backend import (
    DocumentKey,
    DocumentWrite,
    QueryExpectation,
    QueryFilter,
    ReadExpectation,
    StoredDocument,
)
from ip_risk_agent.persistence.core_firestore.repositories import (
    FirestoreControlUnitOfWorkFactory,
)
from ip_risk_agent.persistence.core_firestore.schema import (
    AUDIT_EVENTS,
    CANONICAL_COLLECTIONS,
    MEMBERSHIPS,
    RISK_WORKSPACES,
    USERS,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


class FakeFirestoreBackend:
    """Atomic document backend used without credentials or an emulator."""

    def __init__(self) -> None:
        self.documents: dict[DocumentKey, dict[str, object]] = {}
        self.commits = 0
        self._lock = asyncio.Lock()

    async def get(self, key: DocumentKey) -> StoredDocument | None:
        data = self.documents.get(key)
        return None if data is None else StoredDocument(key, deepcopy(data))

    async def query(
        self, collection: str, filters: tuple[QueryFilter, ...]
    ) -> tuple[StoredDocument, ...]:
        return self._query_from(self.documents, collection, filters)

    async def atomic_commit(
        self,
        *,
        reads: tuple[ReadExpectation, ...],
        queries: tuple[QueryExpectation, ...],
        writes: tuple[DocumentWrite, ...],
    ) -> None:
        async with self._lock:
            for expectation in reads:
                current = self.documents.get(expectation.key)
                if current != expectation.data:
                    raise ConcurrencyConflictError("fake Firestore read conflict")
            for expectation in queries:
                current = self._query_from(
                    self.documents, expectation.collection, expectation.filters
                )
                if current != expectation.documents:
                    raise ConcurrencyConflictError("fake Firestore query conflict")

            updated = deepcopy(self.documents)
            for write in writes:
                if write.operation == "create":
                    if write.key in updated:
                        raise UniqueConstraintViolation("fake Firestore create conflict")
                    assert write.data is not None
                    updated[write.key] = deepcopy(write.data)
                elif write.operation == "set":
                    if write.key not in updated:
                        raise ConcurrencyConflictError("fake Firestore update target disappeared")
                    assert write.data is not None
                    updated[write.key] = deepcopy(write.data)
                else:
                    if write.key not in updated:
                        raise ConcurrencyConflictError("fake Firestore delete target disappeared")
                    del updated[write.key]
            self.documents = updated
            self.commits += 1

    @staticmethod
    def _query_from(documents, collection, filters):
        result = []
        for key, data in documents.items():
            if key.collection != collection or not _matches(data, filters):
                continue
            result.append(StoredDocument(key, deepcopy(data)))
        return tuple(sorted(result, key=lambda item: item.key.document_id))


def _matches(document, filters) -> bool:
    for item in filters:
        if item.operator == "==" and document.get(item.field) != item.value:
            return False
        if item.operator == "in" and document.get(item.field) not in item.value:
            return False
    return True


class SequentialIds:
    def __init__(self) -> None:
        self.current = 0

    def __call__(self, kind: str) -> str:
        self.current += 1
        return f"{kind}-{self.current}"


def make_user(user_id: str, subject: str | None = None) -> User:
    return User(
        user_id,
        subject or f"subject-{user_id}",
        f"{user_id}@example.com",
        user_id,
        NOW,
        NOW,
    )


def make_service(backend: FakeFirestoreBackend) -> WorkspaceAdministrationService:
    return WorkspaceAdministrationService(
        unit_of_work_factory=FirestoreControlUnitOfWorkFactory(backend),
        clock=lambda: NOW,
        id_factory=SequentialIds(),
    )


def in_memory_factory():
    return InMemoryControlStore()


def firestore_factory():
    return FirestoreControlUnitOfWorkFactory(FakeFirestoreBackend())


@pytest.mark.parametrize("factory_builder", (in_memory_factory, firestore_factory))
def test_common_repository_contract_commit_rollback_lookup_and_uniqueness(
    factory_builder,
) -> None:
    async def scenario() -> None:
        factory = factory_builder()
        original = make_user("user-1", "subject-1")
        async with factory() as uow:
            await uow.users.add(original)
            await uow.commit()

        async with factory() as uow:
            assert await uow.users.get("user-1") == original
            assert await uow.users.get_by_google_subject("subject-1") == original
            await uow.users.save(replace(original, display_name="Not Committed"))

        async with factory() as uow:
            assert await uow.users.get("user-1") == original
            with pytest.raises(UniqueConstraintViolation):
                await uow.users.add(make_user("user-2", "subject-1"))

    run(scenario())


def test_firestore_uow_runs_workspace_invitation_contract_without_sdk_types() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        async with factory() as uow:
            await uow.users.add(make_user("owner-1"))
            await uow.users.add(make_user("viewer-1"))
            await uow.commit()

        service = make_service(backend)
        creation = await service.create_workspace(
            owner_user_id="owner-1",
            name="Workspace",
            security_policy_version="security-v1",
            retention_policy_version="retention-v1",
        )
        invitation = await service.invite_member(
            risk_workspace_id=creation.workspace.id,
            actor_user_id="owner-1",
            email="viewer-1@example.com",
            role=MembershipRole.VIEWER,
        )
        await service.accept_invitation(
            invitation_id=invitation.invitation.id,
            authenticated_user_id="viewer-1",
            verified_email="viewer-1@example.com",
        )

        async with factory() as uow:
            assert await uow.workspaces.get(creation.workspace.id) == creation.workspace
            assert await uow.memberships.get(
                creation.workspace.id, "viewer-1"
            ) is not None
            assert len(await uow.audit.list_for_workspace(creation.workspace.id)) == 3

        membership_kinds = {
            document["record_kind"]
            for key, document in backend.documents.items()
            if key.collection == MEMBERSHIPS
        }
        assert membership_kinds == {"membership", "membership_invitation"}
        assert set(key.collection for key in backend.documents) <= set(CANONICAL_COLLECTIONS)

    run(scenario())


def test_firestore_uow_detects_document_lost_update_but_allows_unrelated_writes() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        async with factory() as seed:
            await seed.users.add(make_user("user-1"))
            await seed.commit()

        first = await factory().__aenter__()
        second = await factory().__aenter__()
        original_first = await first.users.get("user-1")
        original_second = await second.users.get("user-1")
        assert original_first is not None and original_second is not None
        await first.users.save(replace(original_first, display_name="First"))
        await second.users.save(replace(original_second, display_name="Second"))
        await first.commit()
        with pytest.raises(ConcurrencyConflictError):
            await second.commit()
        await second.rollback()

        unrelated_one = await factory().__aenter__()
        unrelated_two = await factory().__aenter__()
        await unrelated_one.users.add(make_user("user-2"))
        await unrelated_two.users.add(make_user("user-3"))
        await unrelated_one.commit()
        await unrelated_two.commit()

    run(scenario())


def test_unique_sentinel_prevents_concurrent_google_subject_phantom() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        first = await factory().__aenter__()
        second = await factory().__aenter__()
        await first.users.add(make_user("user-1", "same-subject"))
        await second.users.add(make_user("user-2", "same-subject"))
        await first.commit()
        with pytest.raises(ConcurrencyConflictError):
            await second.commit()
        await second.rollback()
        matches = [
            document
            for key, document in backend.documents.items()
            if key.collection == USERS
            and document.get("google_subject") == "same-subject"
        ]
        assert len(matches) == 1
        sentinels = [
            document
            for key, document in backend.documents.items()
            if key.collection == USERS and document.get("record_kind") == "unique_key"
        ]
        assert sentinels == [
            {
                "schema_version": 1,
                "record_kind": "unique_key",
                "namespace": "google-subject",
                "owner_document_id": "user-1",
            }
        ]

    run(scenario())


def test_cross_aggregate_failure_does_not_publish_partial_firestore_writes() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        existing_audit = AuditEvent(
            "audit-existing",
            "seed-vws",
            AuditEventType.WORKSPACE_CREATED,
            ActorType.USER,
            NOW,
            actor_user_id="owner-1",
        )
        async with factory() as uow:
            await uow.users.add(make_user("owner-1"))
            await uow.audit.append(existing_audit)
            await uow.commit()

        ids = {"workspace": "vws-failed", "audit": "audit-existing"}
        service = WorkspaceAdministrationService(
            unit_of_work_factory=factory,
            clock=lambda: NOW,
            id_factory=ids.__getitem__,
        )
        with pytest.raises(UniqueConstraintViolation):
            await service.create_workspace(
                owner_user_id="owner-1",
                name="Must Roll Back",
                security_policy_version="security-v1",
                retention_policy_version="retention-v1",
            )

        assert DocumentKey(RISK_WORKSPACES, "vws-failed") not in backend.documents
        assert DocumentKey(AUDIT_EVENTS, "audit-existing") in backend.documents

    run(scenario())


def test_member_removal_mount_notification_and_audit_share_firestore_commit() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        workspace = RiskWorkspace(
            "vws-1",
            "Workspace",
            "owner-1",
            "security-v1",
            "retention-v1",
            NOW,
            NOW,
        )
        owner = Membership(
            membership_id_for("vws-1", "owner-1"),
            "vws-1",
            "owner-1",
            MembershipRole.OWNER,
            MembershipStatus.ACTIVE,
            "owner-1",
            NOW,
            NOW,
        )
        manager = Membership(
            membership_id_for("vws-1", "manager-1"),
            "vws-1",
            "manager-1",
            MembershipRole.SOURCE_MANAGER,
            MembershipStatus.ACTIVE,
            "owner-1",
            NOW,
            NOW,
        )
        mount = WorkspaceMount(
            "mount-1",
            "vws-1",
            "source-1",
            "Backend",
            "manager-1",
            "connection-1",
            MountStatus.ACTIVE,
            NOW,
            NOW,
        )
        async with factory() as seed:
            await seed.workspaces.add(workspace)
            await seed.memberships.add(owner)
            await seed.memberships.add(manager)
            await seed.mounts.add(mount)
            await seed.commit()

        service = make_service(backend)
        before = backend.commits
        await service.remove_member(
            risk_workspace_id="vws-1",
            actor_user_id="owner-1",
            target_user_id="manager-1",
        )
        assert backend.commits == before + 1
        async with factory() as uow:
            removed = await uow.memberships.get("vws-1", "manager-1")
            preserved_mount = await uow.mounts.get("mount-1")
            assert removed is not None and removed.status is MembershipStatus.REMOVED
            assert preserved_mount is not None
            assert preserved_mount.status is MountStatus.MANAGER_ACTION_REQUIRED
            assert len(await uow.notifications.list_for_user("owner-1")) == 1
            assert len(await uow.audit.list_for_workspace("vws-1")) == 1

    run(scenario())


def test_append_only_firestore_repositories_have_no_event_mutation_surface() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        async with factory() as uow:
            assert not hasattr(uow.audit, "save")
            assert not hasattr(uow.audit, "delete")
            assert not hasattr(uow.risks, "save_event")
            assert not hasattr(uow.risks, "delete_event")

    run(scenario())


def test_artifact_change_job_and_risk_history_commit_as_one_firestore_transaction() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        artifact = Artifact(
            "artifact-1",
            "vws-1",
            "mount-1",
            "source-1",
            SourceType.GITHUB,
            "path:main.py",
            "main.py",
            "Backend/main.py",
            ArtifactStatus.ACTIVE,
            NOW,
            NOW,
        )
        state = ArtifactState(
            "artifact-1",
            "revision-1",
            "checksum-1",
            ArtifactAvailability.AVAILABLE,
            NOW,
        )
        change = ChangeEvent(
            "change-1",
            "fingerprint-1",
            "vws-1",
            "mount-1",
            "source-1",
            "path:main.py",
            SourceType.GITHUB,
            ChangeType.UPDATE,
            "revision-1",
            None,
            NOW,
            ChangeEventStatus.PENDING,
            0,
            NOW,
            NOW,
            artifact_id="artifact-1",
        )
        job = AnalysisJob(
            "job-1",
            "change-1",
            "artifact-1",
            "revision-1",
            (AnalysisType.PATENT,),
            AnalysisJobStatus.QUEUED,
            NOW,
        )
        risk = Risk(
            "risk-1",
            "vws-1",
            "artifact-1",
            AnalysisType.PATENT,
            "risk-key-1",
            RiskLifecycleState.NEW,
            ReviewDisposition.UNREVIEWED,
            ReviewPriority.HIGH,
            "Potential overlap",
            NOW,
            NOW,
            "job-1",
            NOW,
        )
        evidence = RiskEvidence(
            "evidence-1",
            "risk-1",
            "job-1",
            "result-evidence-1",
            "TEXT",
            "minimal excerpt",
            "segment-1",
            "revision-1",
            NOW,
        )
        event = RiskEvent(
            "risk-event-1",
            "risk-1",
            RiskEventType.DETECTED,
            ActorType.SYSTEM,
            NOW,
            evidence_refs=("evidence-1",),
        )
        before = backend.commits
        async with factory() as uow:
            await uow.artifacts.add(artifact, state)
            await uow.change_events.add(change)
            await uow.analysis_jobs.add(job)
            await uow.risks.add(risk)
            await uow.risks.add_evidence(evidence)
            await uow.risks.append_event(event)
            await uow.commit()
        assert backend.commits == before + 1

        async with factory() as uow:
            assert await uow.artifacts.get("artifact-1") == artifact
            assert await uow.artifacts.get_state("artifact-1") == state
            assert await uow.change_events.get_by_fingerprint("fingerprint-1") == change
            assert await uow.analysis_jobs.list_for_change("change-1") == (job,)
            assert await uow.risks.get_by_key("risk-key-1") == risk
            assert await uow.risks.list_evidence("risk-1") == (evidence,)
            assert await uow.risks.list_events("risk-1") == (event,)

    run(scenario())


def test_optimistic_risk_review_update_and_event_reject_stale_transaction() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        risk = Risk(
            "risk-1",
            "vws-1",
            "artifact-1",
            AnalysisType.PATENT,
            "risk-key-1",
            RiskLifecycleState.NEW,
            ReviewDisposition.UNREVIEWED,
            ReviewPriority.HIGH,
            "Potential overlap",
            NOW,
            NOW,
            "job-1",
            NOW,
        )
        async with factory() as seed:
            await seed.risks.add(risk)
            await seed.commit()

        first = await factory().__aenter__()
        stale = await factory().__aenter__()
        first_risk = await first.risks.get("risk-1")
        stale_risk = await stale.risks.get("risk-1")
        assert first_risk is not None and stale_risk is not None
        await first.risks.save(
            replace(first_risk, review_disposition=ReviewDisposition.MONITORING)
        )
        await first.risks.append_event(
            RiskEvent(
                "review-event-1",
                "risk-1",
                RiskEventType.REVIEW_DISPOSITION_CHANGED,
                ActorType.USER,
                NOW,
                actor_user_id="reviewer-1",
            )
        )
        await stale.risks.save(
            replace(stale_risk, review_disposition=ReviewDisposition.EXCLUDED)
        )
        await first.commit()
        with pytest.raises(ConcurrencyConflictError):
            await stale.commit()
        await stale.rollback()

        async with factory() as verification:
            current = await verification.risks.get("risk-1")
            assert current is not None
            assert current.review_disposition is ReviewDisposition.MONITORING
            assert len(await verification.risks.list_events("risk-1")) == 1

    run(scenario())
