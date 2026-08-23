import { ApiClient, queryString } from "./client";
import type {
  AnalysisProgress,
  Dashboard,
  DataAccessSummary,
  HistoryEntry,
  Invitation,
  Membership,
  Mount,
  NotificationInbox,
  Page,
  Risk,
  RiskDetail,
  Role,
  SecuritySettings,
  User,
  Workspace,
} from "./types";

export class ControlApi {
  constructor(readonly client: ApiClient) {}

  me = () => this.client.request<User>("/api/v1/auth/me");
  googleLoginUrl = () => this.client.url("/api/v1/auth/google/login");
  logout = () =>
    this.client.request<void>("/api/v1/auth/logout", { method: "POST" });
  workspaces = (cursor: string | null = null) =>
    this.client.request<Page<Workspace>>(
      `/api/v1/workspaces${queryString({ cursor })}`,
    );
  workspace = (id: string) =>
    this.client.request<Workspace>(`/api/v1/workspaces/${id}`);
  myMembership = (id: string) =>
    this.client.request<Membership>(`/api/v1/workspaces/${id}/membership`);
  createWorkspace = (body: { name: string; description: string | null }) =>
    this.client.request<Workspace>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify(body),
    });
  dashboard = (id: string) =>
    this.client.request<Dashboard>(`/api/v1/workspaces/${id}/dashboard`);
  analysesProgress = (id: string) =>
    this.client.request<AnalysisProgress>(
      `/api/v1/workspaces/${id}/analyses/progress`,
    );
  invitations = (cursor: string | null = null) =>
    this.client.request<Page<Invitation>>(
      `/api/v1/invitations${queryString({ cursor })}`,
    );
  acceptInvitation = (id: string) =>
    this.client.request<{ workspace: Workspace }>(
      `/api/v1/invitations/${id}/accept`,
      { method: "POST" },
    );
  members = (id: string, cursor: string | null = null) =>
    this.client.request<Page<Membership>>(
      `/api/v1/workspaces/${id}/members${queryString({ cursor })}`,
    );
  invite = (id: string, body: { email: string; role: Role }) =>
    this.client.request<Invitation>(
      `/api/v1/workspaces/${id}/members/invitations`,
      { method: "POST", body: JSON.stringify(body) },
    );
  updateMember = (id: string, userId: string, role: Role) =>
    this.client.request<Membership>(
      `/api/v1/workspaces/${id}/members/${userId}`,
      { method: "PATCH", body: JSON.stringify({ role }) },
    );
  removeMember = (id: string, userId: string) =>
    this.client.request<Membership>(
      `/api/v1/workspaces/${id}/members/${userId}`,
      { method: "DELETE" },
    );
  mounts = (id: string, cursor: string | null = null) =>
    this.client.request<Page<Mount>>(
      `/api/v1/workspaces/${id}/mounts${queryString({ cursor })}`,
    );
  disableMount = (id: string, mountId: string) =>
    this.client.request<Mount>(
      `/api/v1/workspaces/${id}/mounts/${mountId}/disable`,
      { method: "POST" },
    );
  risks = (
    id: string,
    filters: Record<string, string>,
    cursor: string | null = null,
  ) =>
    this.client.request<Page<Risk>>(
      `/api/v1/workspaces/${id}/risks${queryString({ ...filters, cursor })}`,
    );
  risk = (id: string, riskId: string) =>
    this.client.request<RiskDetail>(`/api/v1/workspaces/${id}/risks/${riskId}`);
  reviewRisk = (
    id: string,
    riskId: string,
    body: {
      expected_review_version: number;
      disposition: Risk["review_disposition"];
      comment: string | null;
    },
  ) =>
    this.client.request<Risk>(
      `/api/v1/workspaces/${id}/risks/${riskId}/review`,
      { method: "PATCH", body: JSON.stringify(body) },
    );
  timeline = (id: string, riskId: string) =>
    this.client.request<{ risk: Risk; entries: HistoryEntry[] }>(
      `/api/v1/workspaces/${id}/risks/${riskId}/timeline`,
    );
  history = (
    id: string,
    kind: "activity" | "audit" | "source-access",
    cursor: string | null = null,
  ) =>
    this.client.request<Page<HistoryEntry>>(
      `/api/v1/workspaces/${id}/${kind}${queryString({ cursor })}`,
    );
  exportAuditUrl = (id: string) =>
    this.client.url(`/api/v1/workspaces/${id}/audit/export`);
  security = (id: string) =>
    this.client.request<SecuritySettings>(`/api/v1/workspaces/${id}/security`);
  requestReanalysis = (id: string, changeEventId: string) =>
    this.client.request<{ status: string }>(
      `/api/v1/workspaces/${id}/security/reanalyze`,
      { method: "POST", body: JSON.stringify({ change_event_id: changeEventId }) },
    );
  dataAccess = (id: string) =>
    this.client.request<DataAccessSummary>(
      `/api/v1/workspaces/${id}/security/data-access-summary`,
    );
  updateIgnore = (
    id: string,
    body: { expected_policy_version: string; global_ignore_text: string },
  ) =>
    this.client.request<{ settings: SecuritySettings; changed: boolean }>(
      `/api/v1/workspaces/${id}/security/ipriskignore`,
      { method: "PUT", body: JSON.stringify(body) },
    );
  notifications = (unreadOnly = false, cursor: string | null = null) =>
    this.client.request<NotificationInbox>(
      `/api/v1/notifications${queryString({ unread_only: unreadOnly, cursor })}`,
    );
  markNotificationRead = (id: string) =>
    this.client.request<void>(`/api/v1/notifications/${id}/read`, {
      method: "POST",
    });
}
