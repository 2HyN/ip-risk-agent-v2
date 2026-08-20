"""Workspace-scoped authorization helper shared by Control routers."""

from __future__ import annotations

from ip_risk_agent.application.repositories import (
    ControlUnitOfWorkFactory,
    RecordNotFoundError,
)
from ip_risk_agent.core.memberships import (
    VwsAction,
    authorize_vws_action,
    require_authorized,
)


async def require_workspace_action(
    unit_of_work_factory: ControlUnitOfWorkFactory,
    *,
    risk_workspace_id: str,
    actor_user_id: str,
    action: VwsAction,
):
    async with unit_of_work_factory() as uow:
        workspace = await uow.workspaces.get(risk_workspace_id)
        if workspace is None:
            raise RecordNotFoundError(
                f"workspace was not found: {risk_workspace_id!r}"
            )
        membership = await uow.memberships.get(risk_workspace_id, actor_user_id)
        require_authorized(
            authorize_vws_action(
                actor_user_id=actor_user_id,
                risk_workspace_id=risk_workspace_id,
                membership=membership,
                action=action,
            )
        )
        return workspace, membership


__all__ = ["require_workspace_action"]
