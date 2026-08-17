import { createContext, useContext, type ReactNode } from "react";
import type { Membership, Role, Workspace } from "../shared/api/types";

export type WorkspaceState = {
  workspace: Workspace;
  membership: Membership;
  role: Role;
  canReview: boolean;
  canManageMembers: boolean;
  canManageSecurity: boolean;
  canViewAudit: boolean;
};

const WorkspaceContext = createContext<WorkspaceState | null>(null);

export function WorkspaceProvider({
  value,
  children,
}: {
  value: WorkspaceState;
  children: ReactNode;
}) {
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceState {
  const value = useContext(WorkspaceContext);
  if (value === null)
    throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}

export function capabilities(
  workspace: Workspace,
  membership: Membership,
): WorkspaceState {
  const role = membership.role;
  return {
    workspace,
    membership,
    role,
    canReview: role !== "VIEWER",
    canManageMembers: role === "OWNER",
    canManageSecurity: role === "OWNER",
    canViewAudit: role === "OWNER",
  };
}
