import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useSession } from "../auth/session";
import { humanize } from "../shared/format";
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
          <NavLink to="/notifications">
            Notifications
            <UnreadNotificationBadge />
          </NavLink>
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

/**
 * 안 읽은 알림 수. 모바일 앱 배지처럼 붙는다.
 *
 * 페이지를 옮길 때마다, 그리고 주기적으로 다시 묻는다 — 알림 페이지에서 읽음
 * 처리를 하고 나오면 배지가 그 자리에서 줄어야 한다. 새 알림이 도착하면 브라우저
 * 알림으로도 알린다 — 탭을 보고 있지 않을 때가 알림이 필요한 순간이다.
 */
function UnreadNotificationBadge() {
  const { api, user } = useSession();
  const location = useLocation();
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (user === null) return;
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  }, [user]);
  useEffect(() => {
    if (user === null) return;
    let cancelled = false;
    let timer: number | undefined;
    // 마지막으로 본 알림 시각 — 이후에 생긴 것만 브라우저 알림으로 올린다.
    // 첫 조회는 기준만 잡는다. 접속하자마자 밀린 알림을 쏟아내지 않는다.
    let seenUpTo: string | null = null;
    async function poll(): Promise<void> {
      try {
        const inbox = await api.notifications(true);
        if (!cancelled) {
          setCount(inbox.unread_count);
          const fresh =
            seenUpTo === null
              ? []
              : inbox.items.filter((item) => item.created_at > (seenUpTo ?? ""));
          const latest = inbox.items[0];
          if (latest !== undefined || seenUpTo === null) {
            seenUpTo = latest?.created_at ?? new Date().toISOString();
          }
          if (
            fresh.length > 0 &&
            typeof Notification !== "undefined" &&
            Notification.permission === "granted"
          ) {
            const head = fresh[0];
            const name = head?.metadata_safe["display_name"];
            new Notification("IP Risk Agent", {
              body:
                fresh.length === 1
                  ? `${humanize(head?.notification_type ?? "알림")}${
                      typeof name === "string" && name.length > 0 ? ` · ${name}` : ""
                    }`
                  : `새 알림 ${fresh.length}건`,
              tag: "iprisk-inbox",
            });
          }
        }
      } catch {
        // 배지 하나 때문에 화면을 흔들지 않는다. 다음 주기에 다시 묻는다.
      }
      if (!cancelled) timer = window.setTimeout(() => void poll(), 30_000);
    }
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, user, location.pathname]);
  if (count === 0) return null;
  return (
    <span className="nav-badge" aria-label={`안 읽은 알림 ${count}개`}>
      {count > 99 ? "99+" : count}
    </span>
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
        <NavLink to={`${base}/sources`}>Files</NavLink>
        <NavLink to={`${base}/risks`}>Review</NavLink>
        {sourceNavigation}
        {canManageMembers ? (
          <NavLink to={`${base}/members`}>Members &amp; roles</NavLink>
        ) : null}
        {canViewAudit ? (
          <NavLink to={`${base}/history`}>Activity &amp; audit</NavLink>
        ) : null}
        <NavLink to={`${base}/security`}>Security &amp; data</NavLink>
      </nav>
    </aside>
  );
}
