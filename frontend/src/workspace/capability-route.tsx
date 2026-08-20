import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import type { WorkspaceState } from "./workspace-context";
import { useWorkspace } from "./workspace-context";

export function WorkspaceCapabilityRoute({
  capability,
  children,
}: {
  capability: keyof Pick<
    WorkspaceState,
    "canReview" | "canManageMembers" | "canManageSecurity" | "canViewAudit"
  >;
  children: ReactNode;
}) {
  const state = useWorkspace();
  if (!state[capability])
    return <Navigate to={`/w/${state.workspace.id}`} replace />;
  return <>{children}</>;
}
