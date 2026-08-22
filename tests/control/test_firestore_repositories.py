from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from iprisk_contracts import (
    AnalysisType,
    ChangeType,
    ReviewPriority,
    SourceAccessType,
    SourceArtifactRef,
    SourceChange,
    SourceType,
)
from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
from ip_risk_agent.application.process_change import (
    ChangeEvent,
    ChangeEventStatus,
    InMemoryTaskEnqueuer,
)
from ip_risk_agent.application.process_change.service import (
    SourceChangeDisposition,
    SourceChangeIntakeService,
)
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    InMemoryControlStore,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
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
from ip_risk_agent.core.mounts import (
    MountStatus,
    SourceConnection,
    SourceConnectionStatus,
    SourceWorkspace,
    SourceWorkspaceStatus,
    WorkspaceMount,
)
from ip_risk_agent.core.notifications import (
    Notification,
    NotificationStatus,
    NotificationType,
)
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
from ip_risk_agent.persistence.core_firestore.session import FirestoreDocumentSession
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
        async with factory() as uow:
            assert await uow.memberships.list_invitations_for_email(
                "VIEWER-1@EXAMPLE.COM"
            ) == (invitation.invitation,)
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
            source_change=SourceChange(
                contract_version="1",
                event_id="provider-event-1",
                event_fingerprint="fingerprint-1",
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
            assert await uow.artifacts.list_for_workspace("vws-1") == (artifact,)
            assert await uow.artifacts.list_for_workspace("other-vws") == ()
            assert await uow.change_events.get_by_fingerprint("fingerprint-1") == change
            assert await uow.change_events.list_for_workspace("vws-1") == (change,)
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
            replace(
                first_risk,
                review_disposition=ReviewDisposition.MONITORING,
                review_version=first_risk.review_version + 1,
            )
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
            replace(
                stale_risk,
                review_disposition=ReviewDisposition.EXCLUDED,
                review_version=stale_risk.review_version + 1,
            )
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


def test_artifact_move_transfers_firestore_unique_sentinel_atomically() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        artifact = Artifact(
            "artifact-stable",
            "vws-1",
            "mount-1",
            "source-1",
            SourceType.GITHUB,
            "path:old.py",
            "old.py",
            "Backend/old.py",
            ArtifactStatus.ACTIVE,
            NOW,
            NOW,
        )
        state = ArtifactState(
            artifact.id,
            "revision-1",
            None,
            ArtifactAvailability.AVAILABLE,
            NOW,
        )
        async with factory() as uow:
            await uow.artifacts.add(artifact, state)
            await uow.commit()

        moved = replace(
            artifact,
            source_artifact_id="path:new.py",
            display_name="new.py",
            logical_path="Backend/new.py",
        )
        async with factory() as uow:
            await uow.artifacts.save(moved)
            await uow.commit()

        async with factory() as uow:
            assert await uow.artifacts.get_by_source_identity(
                "source-1", "path:old.py"
            ) is None
            assert await uow.artifacts.get_by_source_identity(
                "source-1", "path:new.py"
            ) == moved

    run(scenario())


def test_source_change_intake_is_idempotent_with_firestore_unit_of_work() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        queue = InMemoryTaskEnqueuer()
        async with factory() as uow:
            await uow.workspaces.add(
                RiskWorkspace(
                    "vws-intake",
                    "Intake workspace",
                    "owner-intake",
                    "security-v1",
                    "retention-v1",
                    NOW,
                    NOW,
                )
            )
            await uow.source_metadata.add_connection(
                SourceConnection(
                    "connection-intake",
                    SourceType.GITHUB,
                    "manager-intake",
                    SourceConnectionStatus.ACTIVE,
                    NOW,
                    NOW,
                )
            )
            await uow.source_metadata.add_source_workspace(
                SourceWorkspace(
                    "source-intake",
                    "connection-intake",
                    SourceType.GITHUB,
                    "repo-intake",
                    "org/repo",
                    SourceWorkspaceStatus.ACTIVE,
                    NOW,
                    NOW,
                )
            )
            await uow.mounts.add(
                WorkspaceMount(
                    "mount-intake",
                    "vws-intake",
                    "source-intake",
                    "Backend",
                    "manager-intake",
                    "connection-intake",
                    MountStatus.ACTIVE,
                    NOW,
                    NOW,
                )
            )
            await uow.commit()

        change = SourceChange(
            contract_version="1",
            event_id="source-event-intake",
            provider_event_id="provider-event-intake",
            event_fingerprint="fingerprint-intake",
            risk_workspace_id="vws-intake",
            mount_id="mount-intake",
            source_workspace_id="source-intake",
            source_type=SourceType.GITHUB,
            artifact=SourceArtifactRef(
                source_artifact_id="repo:path:src/main.py",
                display_name="main.py",
                path_hint="src/main.py",
            ),
            change_type=ChangeType.CREATE,
            revision="revision-intake",
            observed_at=NOW,
            safe_metadata={},
        )
        intake = SourceChangeIntakeService(
            unit_of_work_factory=factory,
            task_enqueuer=queue,
            clock=lambda: NOW,
        )
        first = await intake.register_source_change(change)
        duplicate = await intake.register_source_change(change)
        assert first.disposition is SourceChangeDisposition.CREATED
        assert duplicate.disposition is SourceChangeDisposition.DUPLICATE_PENDING
        assert first.change_event_id == duplicate.change_event_id
        assert first.artifact_id == duplicate.artifact_id
        assert queue.pending_ids == (first.change_event_id,)
        async with factory() as uow:
            event = await uow.change_events.get(first.change_event_id)
            jobs = await uow.analysis_jobs.list_for_change(first.change_event_id)
            assert event is not None and event.status is ChangeEventStatus.PENDING
            assert len(jobs) == 1 and jobs[0].status is AnalysisJobStatus.QUEUED

    run(scenario())


def test_source_access_event_supports_idempotency_lookup_in_firestore() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        event = SourceAccessEvent(
            id="access-1",
            risk_workspace_id="vws-1",
            mount_id="mount-1",
            artifact_id="artifact-1",
            access_type=SourceAccessType.PARTIAL_CONTENT,
            revision="revision-1",
            content_bytes=128,
            occurred_at=NOW,
            analysis_job_id="job-1",
            provider_request_id="request-1",
        )
        async with factory() as uow:
            await uow.audit.append_source_access(event)
            await uow.commit()
        async with factory() as uow:
            assert await uow.audit.get_source_access(event.id) == event
            assert await uow.audit.list_source_access("vws-1") == (event,)

    run(scenario())


def test_firestore_analysis_job_requested_types_can_only_be_narrowed() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        job = AnalysisJob(
            "job-routing",
            "change-routing",
            "artifact-routing",
            "revision-routing",
            (AnalysisType.LICENSE, AnalysisType.PATENT),
            AnalysisJobStatus.QUEUED,
            NOW,
        )
        async with factory() as uow:
            await uow.analysis_jobs.add(job)
            await uow.commit()
        narrowed = replace(
            job,
            requested_analysis_types=(AnalysisType.PATENT,),
        )
        async with factory() as uow:
            await uow.analysis_jobs.save(narrowed)
            await uow.commit()
        async with factory() as uow:
            with pytest.raises(UniqueConstraintViolation, match="only be narrowed"):
                await uow.analysis_jobs.save(job)

    run(scenario())


def test_firestore_history_scope_and_notification_read_invariants() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        risk = Risk(
            "risk-history",
            "vws-history",
            "artifact-history",
            AnalysisType.PATENT,
            "risk-key-history",
            RiskLifecycleState.NEW,
            ReviewDisposition.UNREVIEWED,
            ReviewPriority.HIGH,
            "Potential overlap",
            NOW,
            NOW,
            "job-history",
            NOW,
        )
        notification = Notification(
            "notification-history",
            "user-history",
            "vws-history",
            NotificationType.RISK_HIGH_DETECTED,
            NotificationStatus.UNREAD,
            NOW,
        )
        async with factory() as uow:
            await uow.risks.add(risk)
            await uow.notifications.add(notification)
            await uow.commit()

        async with factory() as uow:
            assert await uow.risks.list_for_workspace("vws-history") == (risk,)
            read = replace(
                notification,
                status=NotificationStatus.READ,
                read_at=NOW,
            )
            await uow.notifications.save(read)
            await uow.commit()

        async with factory() as uow:
            current = await uow.notifications.get(notification.id)
            assert current is not None and current.status is NotificationStatus.READ
            with pytest.raises(UniqueConstraintViolation, match="READ cannot become UNREAD"):
                await uow.notifications.save(notification)

    run(scenario())


def test_firestore_session_and_security_policy_versions_are_monotonic() -> None:
    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        factory = FirestoreControlUnitOfWorkFactory(backend)
        user = make_user("session-user")
        workspace = RiskWorkspace(
            "vws-policy",
            "Workspace",
            user.id,
            "security-v1",
            "retention-v1",
            NOW,
            NOW,
        )
        async with factory() as uow:
            await uow.users.add(user)
            await uow.workspaces.add(workspace)
            await uow.commit()

        async with factory() as uow:
            with pytest.raises(UniqueConstraintViolation, match="session version"):
                await uow.users.save(replace(user, session_version=2))
            with pytest.raises(UniqueConstraintViolation, match="new version"):
                await uow.workspaces.save(
                    replace(workspace, global_ignore_text="/Backend/private/**\n")
                )

        updated_user = replace(user, session_version=1)
        updated_workspace = replace(
            workspace,
            security_policy_version="security-v2",
            global_ignore_text="/Backend/private/**\n",
        )
        async with factory() as uow:
            await uow.users.save(updated_user)
            await uow.workspaces.save(updated_workspace)
            await uow.commit()
        async with factory() as uow:
            assert await uow.users.get(user.id) == updated_user
            assert await uow.workspaces.get(workspace.id) == updated_workspace

    run(scenario())


def test_deleting_and_recreating_the_same_document_in_one_transaction_overwrites() -> None:
    """지웠다가 같은 ID 로 다시 만드는 것은 덮어쓰기다.

    쓰기를 ``create`` 로 남기면 저장소에 아직 있는 문서를 만들려 들고 Firestore 는
    AlreadyExists 로 거부한다. 배포에서 재검사가 자기 근거를 걷어내고 다시 쓸 때
    정확히 이것으로 죽었다 — 세션 안에서는 지워진 것으로 보여 검사를 통과했다.
    """

    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        session = FirestoreDocumentSession(backend)
        await session.create("things", "thing-1", {"value": "first"})
        await session.commit()

        session = FirestoreDocumentSession(backend)
        await session.delete("things", "thing-1")
        await session.create("things", "thing-1", {"value": "second"})
        await session.commit()

        stored = await backend.get(DocumentKey("things", "thing-1"))
        assert stored is not None
        assert stored.data == {"value": "second"}

    asyncio.run(scenario())


def test_creating_and_deleting_the_same_document_in_one_transaction_leaves_nothing() -> None:
    """반대 순서는 없던 일이 되어야 한다. 지울 대상이 저장소에 없다."""

    async def scenario() -> None:
        backend = FakeFirestoreBackend()
        session = FirestoreDocumentSession(backend)
        await session.create("things", "thing-2", {"value": "only"})
        await session.delete("things", "thing-2")
        await session.commit()

        assert await backend.get(DocumentKey("things", "thing-2")) is None

    asyncio.run(scenario())
