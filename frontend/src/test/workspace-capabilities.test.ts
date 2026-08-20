import { describe, expect, it } from "vitest";
import type { Membership, Role, Workspace } from "../shared/api/types";
import { capabilities } from "../workspace/workspace-context";

const workspace: Workspace = {
  id: "vws-1",
  name: "Workspace",
  description: null,
  owner_user_id: "owner-1",
  security_policy_version: "security-v1",
  retention_policy_version: "balanced-v1",
  created_at: "2026-08-17T00:00:00Z",
  updated_at: "2026-08-17T00:00:00Z",
  status: "ACTIVE",
};

function membership(role: Role): Membership {
  return {
    id: `membership-${role}`,
    risk_workspace_id: workspace.id,
    user_id: "user-1",
    role,
    status: "ACTIVE",
    invited_by: "owner-1",
    created_at: workspace.created_at,
    updated_at: workspace.updated_at,
  };
}

describe("workspace UI capabilities", () => {
  it.each([
    ["VIEWER", false, false, false, false],
    ["RISK_REVIEWER", true, false, false, false],
    ["SOURCE_MANAGER", true, false, false, false],
    ["OWNER", true, true, true, true],
  ] as const)(
    "projects %s without creating raw-source authority",
    (role, canReview, canManageMembers, canManageSecurity, canViewAudit) => {
      expect(capabilities(workspace, membership(role))).toMatchObject({
        role,
        canReview,
        canManageMembers,
        canManageSecurity,
        canViewAudit,
      });
    },
  );
});
