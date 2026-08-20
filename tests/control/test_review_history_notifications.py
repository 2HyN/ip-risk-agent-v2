from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from iprisk_contracts import AnalysisType, ReviewPriority, SourceAccessType
from ip_risk_agent.application.history import (
    HistoryQueryService,
    HistoryStream,
    PATH_REDACTION_PLACEHOLDER,
)
from ip_risk_agent.application.notifications import NotificationService
from ip_risk_agent.application.repositories import (
    InMemoryControlStore,
    RecordNotFoundError,
    UniqueConstraintViolation,
)
from ip_risk_agent.application.risk_review import (
    RiskReviewConflictError,
    RiskReviewDisposition,
    RiskReviewService,
)
from ip_risk_agent.application.security_gate import REDACTION_PLACEHOLDER
from ip_risk_agent.core.audit import AuditEvent, AuditEventType, SourceAccessEvent
from ip_risk_agent.core.auth import User
from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.memberships import (
    AuthorizationDeniedError,
    Membership,
    MembershipRole,
    MembershipStatus,
    membership_id_for,
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
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


async def seed_history_context() -> InMemoryControlStore:
    store = InMemoryControlStore()
    async with store() as uow:
        for user_id in ("owner-1", "reviewer-1", "viewer-1", "other-1"):
            await uow.users.add(
                User(
                    id=user_id,
                    google_subject=f"subject-{user_id}",
                    email=f"{user_id}@example.com",
                    display_name=user_id,
                    created_at=NOW,
                    last_login_at=NOW,
                )
            )
        await uow.workspaces.add(
            RiskWorkspace(
                "vws-1",
                "Workspace",
                "owner-1",
                "security-v1",
                "retention-v1",
                NOW,
                NOW,
            )
        )
        for user_id, role in (
            ("owner-1", MembershipRole.OWNER),
            ("reviewer-1", MembershipRole.RISK_REVIEWER),
            ("viewer-1", MembershipRole.VIEWER),
        ):
            await uow.memberships.add(
                Membership(
                    id=membership_id_for("vws-1", user_id),
                    risk_workspace_id="vws-1",
                    user_id=user_id,
                    role=role,
                    status=MembershipStatus.ACTIVE,
                    invited_by="owner-1",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        risk = Risk(
            id="risk-1",
            risk_workspace_id="vws-1",
            artifact_id="artifact-1",
            analysis_type=AnalysisType.PATENT,
            risk_key="risk-key-1",
            lifecycle_state=RiskLifecycleState.EXISTING,
            review_disposition=ReviewDisposition.UNREVIEWED,
            review_priority=ReviewPriority.HIGH,
            summary="Potential overlap",
            first_seen_at=NOW,
            last_seen_at=NOW,
            latest_analysis_job_id="job-1",
            updated_at=NOW,
            latest_evidence_revision="revision-1",
        )
        await uow.risks.add(risk)
        await uow.risks.append_event(
            RiskEvent(
                id="risk-event-detected",
                risk_id=risk.id,
                event_type=RiskEventType.DETECTED,
                actor_type=ActorType.SYSTEM,
                occurred_at=NOW,
                new_state_safe={"lifecycle_state": "EXISTING"},
            )
        )
        await uow.audit.append(
            AuditEvent(
                id="audit-1",
                risk_workspace_id="vws-1",
                event_type=AuditEventType.WORKSPACE_UPDATED,
                actor_type=ActorType.USER,
                actor_user_id="owner-1",
                occurred_at=NOW + timedelta(minutes=1),
                metadata_safe={
                    "access_token": "must-never-export",
                    "source_path": "C:\\Users\\alice\\private\\source.py",
                },
            )
        )
        await uow.audit.append_source_access(
            SourceAccessEvent(
                id="access-1",
                risk_workspace_id="vws-1",
                mount_id="mount-1",
                artifact_id="artifact-1",
                access_type=SourceAccessType.PARTIAL_CONTENT,
                revision="revision-1",
                content_bytes=128,
                occurred_at=NOW + timedelta(minutes=2),
                analysis_job_id="job-1",
                provider_request_id="provider-request-1",
            )
        )
        await uow.notifications.add(
            Notification(
                id="notification-owner",
                user_id="owner-1",
                risk_workspace_id="vws-1",
                notification_type=NotificationType.RISK_HIGH_DETECTED,
                status=NotificationStatus.UNREAD,
                created_at=NOW,
                metadata_safe={"risk_id": "risk-1"},
            )
        )
        await uow.notifications.add(
            Notification(
                id="notification-other",
                user_id="other-1",
                risk_workspace_id="vws-1",
                notification_type=NotificationType.ANALYSIS_FAILED,
                status=NotificationStatus.UNREAD,
                created_at=NOW + timedelta(seconds=1),
            )
        )
        await uow.commit()
    return store


def test_review_update_is_versioned_authorized_and_append_only() -> None:
    async def scenario() -> None:
        store = await seed_history_context()
        service = RiskReviewService(
            unit_of_work_factory=store,
            clock=lambda: NOW + timedelta(minutes=3),
        )
        applied = await service.change_disposition(
            risk_workspace_id="vws-1",
            actor_user_id="reviewer-1",
            risk_id="risk-1",
            expected_review_version=0,
            new_disposition=ReviewDisposition.EXCLUDED,
            comment="API_KEY=top-secret\ninspect C:\\Users\\alice\\source.py",
        )
        assert applied.disposition is RiskReviewDisposition.APPLIED
        assert applied.risk.review_version == 1
        assert applied.risk.lifecycle_state is RiskLifecycleState.EXISTING
        assert applied.event is not None
        assert applied.event.actor_user_id == "reviewer-1"
        assert REDACTION_PLACEHOLDER in (applied.event.reason_safe or "")
        assert PATH_REDACTION_PLACEHOLDER in (applied.event.reason_safe or "")
        assert "top-secret" not in (applied.event.reason_safe or "")
        assert "C:\\Users" not in (applied.event.reason_safe or "")

        unchanged = await service.change_disposition(
            risk_workspace_id="vws-1",
            actor_user_id="reviewer-1",
            risk_id="risk-1",
            expected_review_version=1,
            new_disposition=ReviewDisposition.EXCLUDED,
            comment="does not create a second event",
        )
        assert unchanged.disposition is RiskReviewDisposition.UNCHANGED
        assert unchanged.event is None

        with pytest.raises(RiskReviewConflictError) as stale:
            await service.change_disposition(
                risk_workspace_id="vws-1",
                actor_user_id="reviewer-1",
                risk_id="risk-1",
                expected_review_version=0,
                new_disposition=ReviewDisposition.MONITORING,
            )
        assert stale.value.current_version == 1

        with pytest.raises(AuthorizationDeniedError):
            await service.change_disposition(
                risk_workspace_id="vws-1",
                actor_user_id="viewer-1",
                risk_id="risk-1",
                expected_review_version=1,
                new_disposition=ReviewDisposition.MONITORING,
            )

        async with store() as uow:
            risk = await uow.risks.get("risk-1")
            assert risk is not None
            events = await uow.risks.list_events(risk.id)
            reviews = [
                event
                for event in events
                if event.event_type is RiskEventType.REVIEW_DISPOSITION_CHANGED
            ]
            assert len(reviews) == 1
            with pytest.raises(UniqueConstraintViolation, match="review version"):
                await uow.risks.save(
                    replace(risk, review_disposition=ReviewDisposition.MONITORING)
                )

    run(scenario())


def test_timeline_activity_and_export_keep_streams_separate_and_safe() -> None:
    async def scenario() -> None:
        store = await seed_history_context()
        review = RiskReviewService(
            unit_of_work_factory=store,
            clock=lambda: NOW + timedelta(minutes=3),
        )
        await review.change_disposition(
            risk_workspace_id="vws-1",
            actor_user_id="reviewer-1",
            risk_id="risk-1",
            expected_review_version=0,
            new_disposition=ReviewDisposition.MONITORING,
            comment="reviewed",
        )
        history = HistoryQueryService(
            unit_of_work_factory=store,
            clock=lambda: NOW + timedelta(minutes=4),
        )

        timeline = await history.get_risk_timeline(
            risk_workspace_id="vws-1",
            actor_user_id="viewer-1",
            risk_id="risk-1",
        )
        assert timeline.review_version == 1
        assert timeline.entries[0].event_type == "REVIEW_DISPOSITION_CHANGED"
        assert {entry.stream for entry in timeline.entries} == {HistoryStream.RISK}

        activity = await history.list_workspace_activity(
            risk_workspace_id="vws-1",
            actor_user_id="owner-1",
        )
        assert {entry.stream for entry in activity.entries} == {
            HistoryStream.RISK,
            HistoryStream.AUDIT,
            HistoryStream.SOURCE_ACCESS,
        }
        assert activity.entries == tuple(
            sorted(
                activity.entries,
                key=lambda entry: (entry.occurred_at, entry.stream.value, entry.id),
                reverse=True,
            )
        )
        serialized = repr(activity.entries)
        assert "must-never-export" not in serialized
        assert "C:\\\\Users" not in serialized
        assert REDACTION_PLACEHOLDER in serialized
        assert PATH_REDACTION_PLACEHOLDER in serialized

        exported = await history.export_workspace_history(
            risk_workspace_id="vws-1",
            actor_user_id="owner-1",
        )
        assert exported.entries == activity.entries
        assert exported.generated_at == NOW + timedelta(minutes=4)
        encoded = json.dumps(exported.to_safe_dict(), ensure_ascii=False, sort_keys=True)
        assert "must-never-export" not in encoded
        assert "C:\\\\Users" not in encoded
        assert REDACTION_PLACEHOLDER in encoded
        assert PATH_REDACTION_PLACEHOLDER in encoded

        with pytest.raises(AuthorizationDeniedError):
            await history.list_workspace_activity(
                risk_workspace_id="vws-1",
                actor_user_id="reviewer-1",
            )
        with pytest.raises(AuthorizationDeniedError):
            await history.export_workspace_history(
                risk_workspace_id="vws-1",
                actor_user_id="viewer-1",
            )

    run(scenario())


def test_notification_inbox_is_target_scoped_and_read_is_idempotent() -> None:
    async def scenario() -> None:
        store = await seed_history_context()
        service = NotificationService(
            unit_of_work_factory=store,
            clock=lambda: NOW + timedelta(minutes=5),
        )
        inbox = await service.list_for_user(actor_user_id="owner-1")
        assert inbox.unread_count == 1
        assert [item.id for item in inbox.notifications] == ["notification-owner"]

        with pytest.raises(RecordNotFoundError):
            await service.mark_read(
                actor_user_id="owner-1",
                notification_id="notification-other",
            )

        first = await service.mark_read(
            actor_user_id="owner-1",
            notification_id="notification-owner",
        )
        second = await service.mark_read(
            actor_user_id="owner-1",
            notification_id="notification-owner",
        )
        assert first.changed is True
        assert second.changed is False
        assert first.notification.status is NotificationStatus.READ
        assert first.notification.read_at == NOW + timedelta(minutes=5)

        inbox = await service.list_for_user(
            actor_user_id="owner-1",
            unread_only=True,
        )
        assert inbox.unread_count == 0
        assert inbox.notifications == ()

        async with store() as uow:
            notification = await uow.notifications.get("notification-owner")
            assert notification is not None
            with pytest.raises(UniqueConstraintViolation, match="READ cannot become UNREAD"):
                await uow.notifications.save(
                    replace(
                        notification,
                        status=NotificationStatus.UNREAD,
                        read_at=None,
                    )
                )
            with pytest.raises(UniqueConstraintViolation, match="READ cannot become UNREAD"):
                await uow.notifications.save(
                    replace(
                        notification,
                        read_at=notification.read_at + timedelta(seconds=1),
                    )
                )

    run(scenario())
