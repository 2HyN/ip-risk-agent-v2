"""Workspace Risk list, detail, review, and timeline routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from iprisk_contracts import AnalysisType, ReviewPriority, SourceType
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
    #: 왜 검토가 필요한지. 모델이 쓴 설명이며 판정이 아니다.
    explanation_safe: str | None = None
    #: 앞으로 무엇을 할지. 권고 수준이고 법적 결론이 아니다.
    recommendation_safe: str | None = None
    artifact_display_name: str | None = None
    artifact_logical_path: str | None = None
    mount_id: str | None = None
    mount_alias: str | None = None
    source_type: SourceType | None = None


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
        review_priority: ReviewPriority | None = None,
        mount_id: str | None = None,
        source_type: SourceType | None = None,
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
                            risk.review_disposition is review_disposition
                            if review_disposition is not None
                            # 제외된 Risk 는 기본 목록에서 접는다. 추적이 끊겨
                            # 관리가 끝난 것이라 활성 목록에 섞이면 아직 지켜보는
                            # 것처럼 읽힌다. 지운 것이 아니므로 필터로 부르면 나온다.
                            else risk.review_disposition
                            is not ReviewDisposition.EXCLUDED
                        )
                        and (
                            review_priority is None
                            or risk.review_priority is review_priority
                        )
                    ),
                    key=lambda risk: (risk.updated_at, risk.id),
                    reverse=True,
                )
            )
            projected = []
            artifacts = {}
            mounts = {}
            for risk in values:
                if risk.artifact_id not in artifacts:
                    artifacts[risk.artifact_id] = await uow.artifacts.get(
                        risk.artifact_id
                    )
                artifact = artifacts[risk.artifact_id]
                if artifact is None:
                    mount = None
                else:
                    if artifact.mount_id not in mounts:
                        mounts[artifact.mount_id] = await uow.mounts.get(
                            artifact.mount_id
                        )
                    mount = mounts[artifact.mount_id]
                if mount_id is not None and (mount is None or mount.id != mount_id):
                    continue
                if source_type is not None and (
                    artifact is None or artifact.source_type is not source_type
                ):
                    continue
                projected.append(_risk_response(risk, artifact, mount))
        scope = (
            "risks:"
            f"{vws_id}:{analysis_type}:{lifecycle_state}:{review_disposition}:"
            f"{review_priority}:{mount_id}:{source_type}"
        )
        selected, next_cursor = paginate(
            tuple(projected),
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
            evidence = (
                ()
                if risk is None
                else await uow.risks.list_evidence(
                    risk.id, analysis_job_id=risk.latest_analysis_job_id
                )
            )
            artifact = None if risk is None else await uow.artifacts.get(risk.artifact_id)
            mount = None if artifact is None else await uow.mounts.get(artifact.mount_id)
        if risk is None or risk.risk_workspace_id != vws_id:
            raise RecordNotFoundError(f"risk was not found: {risk_id!r}")
        response.headers["ETag"] = opaque_etag(
            "risk-review",
            str(risk.review_version),
        )
        return RiskDetailResponse(
            risk=_risk_response(risk, artifact, mount),
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
            artifact = None if risk is None else await uow.artifacts.get(risk.artifact_id)
            mount = None if artifact is None else await uow.mounts.get(artifact.mount_id)
        assert risk is not None
        return RiskTimelineResponse(
            risk=_risk_response(risk, artifact, mount),
            entries=[HistoryEntryResponse.from_entry(item) for item in timeline.entries],
        )

    return router


def _risk_response(risk, artifact, mount) -> RiskResponse:
    return RiskResponse(
        **RiskResponse.model_validate(risk).model_dump(
            exclude={
                "artifact_display_name",
                "artifact_logical_path",
                "mount_id",
                "mount_alias",
                "source_type",
            }
        ),
        artifact_display_name=None if artifact is None else artifact.display_name,
        artifact_logical_path=None if artifact is None else artifact.logical_path,
        mount_id=None if mount is None else mount.id,
        mount_alias=None if mount is None else mount.alias,
        source_type=None if artifact is None else artifact.source_type,
    )


__all__ = ["RiskResponse", "RiskRouterDependencies", "create_risks_router"]
