"""Agent 1 workspace API namespace."""

from .router import (
    WorkspaceResponse,
    WorkspaceRouterDependencies,
    create_invitations_router,
    create_workspaces_router,
)

__all__ = [
    "WorkspaceResponse",
    "WorkspaceRouterDependencies",
    "create_invitations_router",
    "create_workspaces_router",
]

