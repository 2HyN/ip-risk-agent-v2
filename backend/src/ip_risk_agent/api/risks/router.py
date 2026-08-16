"""Workspace Risk list, detail, review, and timeline routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from iprisk_contracts import AnalysisType, ReviewPriority
from pydantic import Field

from ip_risk_agent.application.auth import AuthenticationService
from ip_risk_agent.application.history import HistoryQueryService
from ip_risk_agent.application.repositories import (
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.application.risk_review import RiskReviewService
from ip_risk_agent.core.memberships import VwsAction
from ip_risk_agent.core.risk import ReviewDisposition, RiskLifecycleState

from ..authorization import require_workspace_action
from ..common import (
    CsrfGuard,
    CursorCodec,
    CurrentPrincipal,
    CurrentPrincipalDependency,
    Page,
    StrictApiModel,
    opaque_etag,
    paginate,
)
from ..history.models import HistoryEntryResponse


class RiskResponse(StrictApiModel):
    id: str
    risk_workspace_id: str
    artifact_id: str
    analysis_type: AnalysisType
    lifecycle_state: RiskLifecycleState
    review_disposition: ReviewDisposition
    review_priority: ReviewPriority
    summary: str
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    review_version: int
    latest_analysis_job_id: str
    latest_evidence_revision: str | None


class EvidenceResponse(StrictApiModel):
    id: str
    evidence_type: str
    excerpt: str
    reference: str
    source_revision: str
    created_at: datetime
    metadata_safe: dict[str, object]


class OpenOriginalAction(StrictApiModel):
    action: str = "SOURCE_OPEN_ORIGINAL"
    artifact_id: str


class RiskDetailResponse(StrictApiModel):
    risk: RiskResponse
    evidence: list[EvidenceResponse]
    open_original: OpenOriginalAction


class ReviewUpdateRequest(StrictApiModel):
    expected_review_version: int = Field(ge=0)
    disposition: ReviewDisposition
    comment: str | None = Field(default=None, max_length=2_000)


class RiskTimelineResponse(StrictApiModel):
    risk: RiskResponse
    entries: list[HistoryEntryResponse]


@dataclass(frozen=True, slots=True)
class RiskRouterDependencies:
    unit_of_work_factory: ControlUnitOfWorkFactory
    review: RiskReviewService
    history: HistoryQueryService
    authentication: AuthenticationService
    cursor_codec: CursorCodec


def create_risks_router(deps: RiskRouterDependencies) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/workspaces/{vws_id}/risks",
        tags=["risks"],
    )
    current = CurrentPrincipalDependency(deps.authentication)
    csrf = CsrfGuard()

    @router.get("", response_model=Page[RiskResponse])
    async def list_risks(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        analysis_type: AnalysisType | None = None,
        lifecycle_state: RiskLifecycleState | None = None,
        review_disposition: ReviewDisposition | None = None,
    ):
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.RISK_VIEW,
        )
        async with deps.unit_of_work_factory() as uow:
            values = await uow.risks.list_for_workspace(vws_id)
        values = tuple(
            sorted(
                (
                    risk
                    for risk in values
                    if (analysis_type is None or risk.analysis_type is analysis_type)
                    and (
                        lifecycle_state is None
                        or risk.lifecycle_state is lifecycle_state
                    )
                    and (
                        review_disposition is None
                        or risk.review_disposition is review_disposition
                    )
                ),
                key=lambda risk: (risk.updated_at, risk.id),
                reverse=True,
            )
        )
        scope = (
            f"risks:{vws_id}:{analysis_type}:{lifecycle_state}:{review_disposition}"
        )
        selected, next_cursor = paginate(
            values,
            cursor=cursor,
            limit=limit,
            scope=scope,
            codec=deps.cursor_codec,
        )
        return Page(items=list(selected), next_cursor=next_cursor)

    @router.get("/{risk_id}", response_model=RiskDetailResponse)
    async def get_risk(
        vws_id: str,
        risk_id: str,
        response: Response,
        principal: CurrentPrincipal = Depends(current),
    ):
        await require_workspace_action(
            deps.unit_of_work_factory,
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            action=VwsAction.RISK_VIEW,
        )
        async with deps.unit_of_work_factory() as uow:
            risk = await uow.risks.get(risk_id)
            evidence = () if risk is None else await uow.risks.list_evidence(risk.id)
        if risk is None or risk.risk_workspace_id != vws_id:
            raise RecordNotFoundError(f"risk was not found: {risk_id!r}")
        response.headers["ETag"] = opaque_etag(
            "risk-review",
            str(risk.review_version),
        )
        return RiskDetailResponse(
            risk=RiskResponse.model_validate(risk),
            evidence=[EvidenceResponse.model_validate(item) for item in evidence],
            open_original=OpenOriginalAction(artifact_id=risk.artifact_id),
        )

    @router.patch("/{risk_id}/review", response_model=RiskResponse)
    async def review_risk(
        vws_id: str,
        risk_id: str,
        body: ReviewUpdateRequest,
        response: Response,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        result = await deps.review.change_disposition(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            risk_id=risk_id,
            expected_review_version=body.expected_review_version,
            new_disposition=body.disposition,
            comment=body.comment,
        )
        response.headers["ETag"] = opaque_etag(
            "risk-review",
            str(result.risk.review_version),
        )
        return result.risk

    @router.get("/{risk_id}/timeline", response_model=RiskTimelineResponse)
    async def risk_timeline(
        vws_id: str,
        risk_id: str,
        principal: CurrentPrincipal = Depends(current),
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ):
        timeline = await deps.history.get_risk_timeline(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            risk_id=risk_id,
            limit=limit,
        )
        async with deps.unit_of_work_factory() as uow:
            risk = await uow.risks.get(risk_id)
        assert risk is not None
        return RiskTimelineResponse(
            risk=RiskResponse.model_validate(risk),
            entries=[HistoryEntryResponse.from_entry(item) for item in timeline.entries],
        )

    return router


__all__ = ["RiskResponse", "RiskRouterDependencies", "create_risks_router"]
