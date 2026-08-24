"""Authorized timeline, workspace activity, and safe history export queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ip_risk_agent.application.repositories import (
    ControlUnitOfWork,
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.audit import AuditEvent, SourceAccessEvent
from ip_risk_agent.core.common import ActorType, normalize_utc
from ip_risk_agent.core.memberships import (
    VwsAction,
    authorize_vws_action,
    require_authorized,
)
from ip_risk_agent.core.risk import Risk, RiskEvent

from .models import (
    HistoryEntry,
    HistoryExport,
    HistoryStream,
    RiskTimeline,
    WorkspaceActivity,
)
from .safety import HistorySafetyPolicy, sanitize_history_mapping

Clock = Callable[[], datetime]


class HistoryQueryService:
    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        clock: Clock,
        safety_policy: HistorySafetyPolicy | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._safety = safety_policy or HistorySafetyPolicy()

    async def get_risk_timeline(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        risk_id: str,
        limit: int = 100,
    ) -> RiskTimeline:
        _require_limit(limit)
        async with self._unit_of_work_factory() as uow:
            await _authorize(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.RISK_VIEW,
            )
            risk = await uow.risks.get(risk_id)
            if risk is None or risk.risk_workspace_id != risk_workspace_id:
                raise RecordNotFoundError(f"risk was not found: {risk_id!r}")
            events = await uow.risks.list_events(risk.id)
        entries = tuple(
            _risk_entry(risk, event, self._safety)
            for event in _newest(events, limit)
        )
        return RiskTimeline(
            risk_id=risk.id,
            risk_workspace_id=risk.risk_workspace_id,
            lifecycle_state=risk.lifecycle_state,
            review_disposition=risk.review_disposition,
            review_version=risk.review_version,
            entries=entries,
        )

    async def list_workspace_activity(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        limit: int = 100,
    ) -> WorkspaceActivity:
        entries = await self._workspace_entries(
            risk_workspace_id=risk_workspace_id,
            actor_user_id=actor_user_id,
            action=VwsAction.AUDIT_VIEW,
            limit=limit,
        )
        return WorkspaceActivity(risk_workspace_id, entries)

    async def list_risk_events(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        limit: int = 100,
    ) -> WorkspaceActivity:
        """Risk 생애 사건만. 전체 활동에서는 접근 기록에 묻힌다."""
        _require_limit(limit)
        async with self._unit_of_work_factory() as uow:
            await _authorize(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.AUDIT_VIEW,
            )
            risks = await uow.risks.list_for_workspace(risk_workspace_id)
            risk_events = []
            for risk in risks:
                risk_events.extend(
                    (risk, event) for event in await uow.risks.list_events(risk.id)
                )
        entries = tuple(
            sorted(
                (
                    _risk_entry(risk, event, self._safety)
                    for risk, event in risk_events
                ),
                key=lambda entry: (entry.occurred_at, entry.id),
                reverse=True,
            )[:limit]
        )
        return WorkspaceActivity(risk_workspace_id, entries)

    async def list_audit_events(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        limit: int = 100,
    ) -> WorkspaceActivity:
        _require_limit(limit)
        async with self._unit_of_work_factory() as uow:
            await _authorize(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.AUDIT_VIEW,
            )
            events = await uow.audit.list_for_workspace(risk_workspace_id)
        entries = tuple(
            _audit_entry(event, self._safety)
            for event in sorted(
                events,
                key=lambda event: (event.occurred_at, event.id),
                reverse=True,
            )[:limit]
        )
        return WorkspaceActivity(risk_workspace_id, entries)

    async def list_source_access_events(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        limit: int = 100,
    ) -> WorkspaceActivity:
        _require_limit(limit)
        async with self._unit_of_work_factory() as uow:
            await _authorize(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=VwsAction.AUDIT_VIEW,
            )
            events = await uow.audit.list_source_access(risk_workspace_id)
        entries = tuple(
            _access_entry(event, self._safety)
            for event in sorted(
                events,
                key=lambda event: (event.occurred_at, event.id),
                reverse=True,
            )[:limit]
        )
        return WorkspaceActivity(risk_workspace_id, entries)

    async def export_workspace_history(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        limit: int = 500,
    ) -> HistoryExport:
        entries = await self._workspace_entries(
            risk_workspace_id=risk_workspace_id,
            actor_user_id=actor_user_id,
            action=VwsAction.AUDIT_EXPORT,
            limit=limit,
        )
        return HistoryExport(
            risk_workspace_id=risk_workspace_id,
            generated_at=normalize_utc(self._clock(), "history_export.clock"),
            entries=entries,
        )

    async def _workspace_entries(
        self,
        *,
        risk_workspace_id: str,
        actor_user_id: str,
        action: VwsAction,
        limit: int,
    ) -> tuple[HistoryEntry, ...]:
        _require_limit(limit)
        async with self._unit_of_work_factory() as uow:
            await _authorize(
                uow,
                risk_workspace_id=risk_workspace_id,
                actor_user_id=actor_user_id,
                action=action,
            )
            risks = await uow.risks.list_for_workspace(risk_workspace_id)
            risk_events = []
            for risk in risks:
                risk_events.extend(
                    (risk, event) for event in await uow.risks.list_events(risk.id)
                )
            audit_events = await uow.audit.list_for_workspace(risk_workspace_id)
            access_events = await uow.audit.list_source_access(risk_workspace_id)

        entries = [
            _risk_entry(risk, event, self._safety)
            for risk, event in risk_events
        ]
        entries.extend(_audit_entry(event, self._safety) for event in audit_events)
        entries.extend(_access_entry(event, self._safety) for event in access_events)
        return tuple(
            sorted(
                entries,
                key=lambda entry: (entry.occurred_at, entry.stream.value, entry.id),
                reverse=True,
            )[:limit]
        )


async def _authorize(
    uow: ControlUnitOfWork,
    *,
    risk_workspace_id: str,
    actor_user_id: str,
    action: VwsAction,
) -> None:
    if await uow.workspaces.get(risk_workspace_id) is None:
        raise RecordNotFoundError(f"workspace was not found: {risk_workspace_id!r}")
    membership = await uow.memberships.get(risk_workspace_id, actor_user_id)
    require_authorized(
        authorize_vws_action(
            actor_user_id=actor_user_id,
            risk_workspace_id=risk_workspace_id,
            membership=membership,
            action=action,
        )
    )


def _risk_entry(
    risk: Risk,
    event: RiskEvent,
    safety: HistorySafetyPolicy,
) -> HistoryEntry:
    return HistoryEntry(
        id=event.id,
        stream=HistoryStream.RISK,
        event_type=event.event_type.value,
        risk_workspace_id=risk.risk_workspace_id,
        occurred_at=event.occurred_at,
        actor_type=event.actor_type,
        actor_user_id=event.actor_user_id,
        risk_id=risk.id,
        # 화면이 id 를 파일 이름으로 되짚을 열쇠. 이것이 없으면 로그가 해시
        # 덩어리로만 보인다 — 사건은 파일에서 났는데 파일을 말하지 않았다.
        artifact_id=risk.artifact_id,
        metadata_safe=sanitize_history_mapping(
            {
                "previous_state": event.previous_state_safe,
                "new_state": event.new_state_safe,
                "analysis_job_id": event.analysis_job_id,
                "evidence_refs": event.evidence_refs,
                "reason": event.reason_safe,
                # 사람이 읽는 로그의 본문. Risk 를 열지 않고도 무엇이 감지·해소
                # 됐는지 알 수 있어야 한다.
                "analysis_type": risk.analysis_type.value,
                "summary": risk.summary,
            },
            safety,
        ),
    )


def _audit_entry(event: AuditEvent, safety: HistorySafetyPolicy) -> HistoryEntry:
    return HistoryEntry(
        id=event.id,
        stream=HistoryStream.AUDIT,
        event_type=event.event_type.value,
        risk_workspace_id=event.risk_workspace_id,
        occurred_at=event.occurred_at,
        actor_type=event.actor_type,
        actor_user_id=event.actor_user_id,
        metadata_safe=sanitize_history_mapping(event.metadata_safe, safety),
    )


def _access_entry(
    event: SourceAccessEvent,
    safety: HistorySafetyPolicy,
) -> HistoryEntry:
    return HistoryEntry(
        id=event.id,
        stream=HistoryStream.SOURCE_ACCESS,
        event_type=event.access_type.value,
        risk_workspace_id=event.risk_workspace_id,
        occurred_at=event.occurred_at,
        actor_type=ActorType.SYSTEM,
        artifact_id=event.artifact_id,
        mount_id=event.mount_id,
        metadata_safe=sanitize_history_mapping(
            {
                "analysis_job_id": event.analysis_job_id,
                "content_bytes": event.content_bytes,
                "provider_request_id": event.provider_request_id,
                "revision": event.revision,
            },
            safety,
        ),
    )


def _newest(events: tuple[RiskEvent, ...], limit: int) -> tuple[RiskEvent, ...]:
    return tuple(
        sorted(events, key=lambda event: (event.occurred_at, event.id), reverse=True)[
            :limit
        ]
    )


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or limit < 1 or limit > 10_000:
        raise ValueError("history limit must be between 1 and 10000")


__all__ = ["HistoryQueryService"]
