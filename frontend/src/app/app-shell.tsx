import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { useSession } from "../auth/session";
import { Badge, Button, ErrorState, LoadingState } from "../shared/ui";
import { useResource } from "../shared/hooks/use-resource";
import {
  WorkspaceProvider,
  capabilities,
  useWorkspace,
} from "../workspace/workspace-context";
import { useIntegration } from "./integration-context";

export function AppShell() {
  const { user, logout } = useSession();
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="topbar__brand" onClick={() => navigate("/")}>
          <span className="brand-mark">IP</span>
          <span>IP Risk Agent</span>
        </button>
        <nav className="topbar__nav" aria-label="Global navigation">
          <NavLink to="/">Workspaces</NavLink>
          <NavLink to="/notifications">Notifications</NavLink>
        </nav>
        <div className="account">
          <div className="account__avatar">
            {user?.avatar_url === null || user?.avatar_url === undefined ? (
              user?.display_name.slice(0, 1)
            ) : (
              <img src={user.avatar_url} alt="" />
            )}
          </div>
          <div>
            <strong>{user?.display_name}</strong>
            <span>{user?.email}</span>
          </div>
          <Button
            variant="ghost"
            onClick={() => {
              void logout().then(() => navigate("/login"));
            }}
          >
            Sign out
          </Button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}

export function WorkspaceLayout() {
  const { workspaceId = "" } = useParams();
  const { api, user } = useSession();
  const integration = useIntegration();
  const resource = useResource(async () => {
    const [workspace, membership] = await Promise.all([
      api.workspace(workspaceId),
      api.myMembership(workspaceId),
    ]);
    if (membership.user_id !== user?.id)
      throw new Error("Your active workspace membership was not found.");
    return capabilities(workspace, membership);
  }, [api, workspaceId, user?.id]);
  if (resource.loading)
    return (
      <main className="center-page">
        <LoadingState label="Opening workspace" />
      </main>
    );
  if (resource.error !== null)
    return (
      <main className="content">
        <ErrorState error={resource.error} retry={resource.reload} />
      </main>
    );
  if (resource.data === null) return null;
  return (
    <WorkspaceProvider value={resource.data}>
      <div className="workspace-shell">
        <WorkspaceSidebar sourceNavigation={integration.sourceNavigation} />
        <main className="workspace-main">
          <Outlet />
        </main>
      </div>
    </WorkspaceProvider>
  );
}

function WorkspaceSidebar({
  sourceNavigation,
}: {
  sourceNavigation?: React.ReactNode;
}) {
  const { workspace, role, canManageMembers, canViewAudit } = useWorkspace();
  const base = `/w/${workspace.id}`;
  return (
    <aside className="sidebar">
      <div className="sidebar__workspace">
        <span className="workspace-card__icon">
          {workspace.name.slice(0, 2).toUpperCase()}
        </span>
        <div>
          <strong>{workspace.name}</strong>
          <Badge tone="neutral">{role.replaceAll("_", " ")}</Badge>
        </div>
      </div>
      <nav aria-label="Workspace navigation">
        <NavLink end to={base}>
          Overview
        </NavLink>
        <NavLink to={`${base}/risks`}>Risks</NavLink>
        <NavLink to={`${base}/sources`}>Sources</NavLink>
        {sourceNavigation}
        {canManageMembers ? (
          <NavLink to={`${base}/members`}>Members &amp; roles</NavLink>
        ) : null}
        {canViewAudit ? (
          <NavLink to={`${base}/history`}>Activity &amp; audit</NavLink>
        ) : null}
        <NavLink to={`${base}/security`}>Security &amp; data</NavLink>
      </nav>
      <div className="sidebar__footer">
        <span>Control Plane</span>
        <small>Raw source is never previewed here.</small>
      </div>
    </aside>
  );
}
