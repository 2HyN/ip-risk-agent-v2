"""VWS security policy and data-access transparency routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from iprisk_contracts import SourceAccessType
from pydantic import Field

from ip_risk_agent.application.auth import AuthenticationService
from ip_risk_agent.application.history.safety import (
    HistorySafetyPolicy,
    sanitize_history_text,
)
from ip_risk_agent.application.security_policy import WorkspaceSecurityService

from ..common import (
    CsrfGuard,
    CurrentPrincipal,
    CurrentPrincipalDependency,
    StrictApiModel,
    opaque_etag,
)
from ..workspaces.router import MountResponse


class SecuritySettingsResponse(StrictApiModel):
    risk_workspace_id: str
    policy_version: str
    global_ignore_text: str
    rule_count: int


class SecurityPolicyUpdateRequest(StrictApiModel):
    expected_policy_version: str = Field(min_length=1, max_length=200)
    global_ignore_text: str = Field(max_length=64_000)


class SecurityPolicyUpdateResponse(StrictApiModel):
    settings: SecuritySettingsResponse
    changed: bool


class SourceAccessResponse(StrictApiModel):
    id: str
    risk_workspace_id: str
    mount_id: str
    artifact_id: str
    analysis_job_id: str | None
    access_type: SourceAccessType
    revision: str
    content_bytes: int
    provider_request_id: str | None
    occurred_at: datetime

    @classmethod
    def from_event(cls, event):
        safety = HistorySafetyPolicy()
        return cls(
            id=event.id,
            risk_workspace_id=event.risk_workspace_id,
            mount_id=event.mount_id,
            artifact_id=event.artifact_id,
            analysis_job_id=(
                None
                if event.analysis_job_id is None
                else sanitize_history_text(event.analysis_job_id, safety)
            ),
            access_type=event.access_type,
            revision=sanitize_history_text(event.revision, safety),
            content_bytes=event.content_bytes,
            provider_request_id=(
                None
                if event.provider_request_id is None
                else sanitize_history_text(event.provider_request_id, safety)
            ),
            occurred_at=event.occurred_at,
        )


class DataAccessSummaryResponse(StrictApiModel):
    risk_workspace_id: str
    retention_policy_version: str
    policy_version: str
    mounts: list[MountResponse]
    connected_sources: list["ConnectedSourceResponse"]
    recent_access: list[SourceAccessResponse]
    raw_source_persisted: bool
    analysis_artifact_persisted: bool
    external_rag_reference_only: bool


class ConnectedSourceResponse(StrictApiModel):
    mount_id: str
    alias: str
    source_type: str | None
    provider_account_label: str | None
    status: str
    tracking_scope_summary: dict[str, object]
    mounted_by_user_id: str


@dataclass(frozen=True, slots=True)
class SecurityRouterDependencies:
    security: WorkspaceSecurityService
    authentication: AuthenticationService


def create_security_router(deps: SecurityRouterDependencies) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/workspaces/{vws_id}/security",
        tags=["security"],
    )
    current = CurrentPrincipalDependency(deps.authentication)
    csrf = CsrfGuard()

    @router.get("", response_model=SecuritySettingsResponse)
    async def get_security(
        vws_id: str,
        response: Response,
        principal: CurrentPrincipal = Depends(current),
    ):
        settings = await deps.security.get_settings(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
        )
        response.headers["ETag"] = opaque_etag(
            "security-policy",
            settings.policy_version,
        )
        return settings

    @router.put("/ipriskignore", response_model=SecurityPolicyUpdateResponse)
    async def update_ipriskignore(
        vws_id: str,
        body: SecurityPolicyUpdateRequest,
        response: Response,
        principal: CurrentPrincipal = Depends(current),
        _csrf: None = Depends(csrf),
    ):
        result = await deps.security.update_ignore_policy(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            expected_policy_version=body.expected_policy_version,
            global_ignore_text=body.global_ignore_text,
        )
        response.headers["ETag"] = opaque_etag(
            "security-policy",
            result.settings.policy_version,
        )
        return result

    @router.get("/data-access-summary", response_model=DataAccessSummaryResponse)
    async def data_access_summary(
        vws_id: str,
        principal: CurrentPrincipal = Depends(current),
        access_limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        summary = await deps.security.get_data_access_summary(
            risk_workspace_id=vws_id,
            actor_user_id=principal.user.id,
            access_limit=access_limit,
        )
        return DataAccessSummaryResponse(
            risk_workspace_id=summary.risk_workspace_id,
            retention_policy_version=summary.retention_policy_version,
            policy_version=summary.policy_version,
            mounts=[MountResponse.model_validate(item) for item in summary.mounts],
            connected_sources=[
                ConnectedSourceResponse(
                    mount_id=item.mount.id,
                    alias=item.mount.alias,
                    source_type=(
                        None if item.source_type is None else item.source_type.value
                    ),
                    provider_account_label=item.provider_account_label,
                    status=item.mount.status.value,
                    tracking_scope_summary=dict(item.tracking_scope_summary),
                    mounted_by_user_id=item.mount.mounted_by_user_id,
                )
                for item in summary.connected_sources
            ],
            recent_access=[
                SourceAccessResponse.from_event(item) for item in summary.recent_access
            ],
            raw_source_persisted=summary.raw_source_persisted,
            analysis_artifact_persisted=summary.analysis_artifact_persisted,
            external_rag_reference_only=summary.external_rag_reference_only,
        )

    return router


__all__ = ["SecurityRouterDependencies", "create_security_router"]
