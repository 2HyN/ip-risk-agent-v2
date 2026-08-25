export type Page<T> = { items: T[]; next_cursor: string | null };

export type User = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  csrf_token: string;
};

export type Workspace = {
  id: string;
  name: string;
  description: string | null;
  owner_user_id: string;
  security_policy_version: string;
  retention_policy_version: string;
  created_at: string;
  updated_at: string;
  status: "ACTIVE" | "DELETING" | "DELETED";
  // 목록 라우트만 채운다 — 각 workspace 에서 내가 맡은 역할.
  my_role?: Role | null;
};

export type Role = "OWNER" | "SOURCE_MANAGER" | "RISK_REVIEWER" | "VIEWER";
export type Membership = {
  id: string;
  risk_workspace_id: string;
  user_id: string;
  role: Role;
  status: "INVITED" | "ACTIVE" | "REMOVED";
  invited_by: string;
  created_at: string;
  updated_at: string;
  // 목록 라우트만 채운다 — id 는 사람이 못 알아본다.
  user_email?: string | null;
  user_display_name?: string | null;
  invited_by_email?: string | null;
};

export type Invitation = {
  id: string;
  risk_workspace_id: string;
  workspace_name: string;
  acceptance_available: boolean;
  email: string;
  role: Role;
  status: "PENDING" | "ACCEPTED" | "REVOKED" | "EXPIRED";
  invited_by: string;
  invited_by_email?: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
};

export type Mount = {
  id: string;
  risk_workspace_id: string;
  source_workspace_id: string;
  alias: string;
  mounted_by_user_id: string;
  source_connection_id: string;
  status:
    | "ACTIVE"
    | "REAUTH_REQUIRED"
    | "MANAGER_ACTION_REQUIRED"
    | "SOURCE_OFFLINE"
    | "DISABLED";
  created_at: string;
  updated_at: string;
};

export type Risk = {
  id: string;
  risk_workspace_id: string;
  artifact_id: string;
  analysis_type: "PATENT" | "LICENSE";
  lifecycle_state: "NEW" | "EXISTING" | "RESOLVED";
  review_disposition:
    | "UNREVIEWED"
    | "MONITORING"
    | "ACCEPTED_RISK"
    | "EXCLUDED";
  review_priority: "HIGH" | "INDETERMINATE" | "MEDIUM" | "LOW";
  summary: string;
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
  resolved_at: string | null;
  review_version: number;
  latest_analysis_job_id: string;
  latest_evidence_revision: string | null;
  explanation_safe: string | null;
  recommendation_safe: string | null;
  artifact_display_name: string | null;
  artifact_logical_path: string | null;
  mount_id: string | null;
  mount_alias: string | null;
  source_type: "GOOGLE_DRIVE" | "GITHUB" | "LOCAL" | null;
};

export type Evidence = {
  id: string;
  evidence_type: string;
  excerpt: string;
  reference: string;
  source_revision: string;
  created_at: string;
  metadata_safe: Record<string, unknown>;
};

export type RiskDetail = {
  risk: Risk;
  evidence: Evidence[];
  open_original: { action: "SOURCE_OPEN_ORIGINAL"; artifact_id: string };
};

export type HistoryEntry = {
  id: string;
  stream: string;
  event_type: string;
  risk_workspace_id: string;
  occurred_at: string;
  actor_type: string;
  actor_user_id: string | null;
  risk_id: string | null;
  artifact_id: string | null;
  mount_id: string | null;
  metadata_safe: Record<string, unknown>;
};

export type Dashboard = {
  new_risks: number;
  monitoring_risks: number;
  resolved_recently: number;
  analysis_failed: number;
  source_health: {
    active: number;
    action_required: number;
    offline: number;
    disabled: number;
  };
};

export type SecuritySettings = {
  risk_workspace_id: string;
  policy_version: string;
  global_ignore_text: string;
  rule_count: number;
};

export type SourceAccess = {
  id: string;
  mount_id: string;
  artifact_id: string;
  access_type: string;
  revision: string;
  content_bytes: number;
  occurred_at: string;
};

export type ConnectedSource = {
  mount_id: string;
  alias: string;
  source_type: string | null;
  provider_account_label: string | null;
  status: string;
  tracking_scope_summary: Record<string, unknown>;
  mounted_by_user_id: string;
};

export type TrackedArtifact = {
  artifact_id: string;
  change_event_id: string | null;
  mount_id: string;
  source_type: string;
  source_context: string | null;
  display_name: string;
  logical_path: string;
  availability: string;
  latest_revision: string | null;
  change_status: string | null;
  analysis_status: string | null;
  analysis_failure_safe: string | null;
  risk_count: number;
  active_risk_count: number;
  first_risk_id: string | null;
  highest_risk_priority: string | null;
  updated_at: string;
};

export type DataAccessSummary = {
  risk_workspace_id: string;
  retention_policy_version: string;
  policy_version: string;
  mounts: Mount[];
  connected_sources: ConnectedSource[];
  tracked_artifacts: TrackedArtifact[];
  recent_access: SourceAccess[];
  raw_source_persisted: false;
  analysis_artifact_persisted: false;
  external_rag_reference_only: true;
};

export type AnalysisProgressItem = {
  artifact_id: string;
  display_name: string;
  status: string;
  failure_safe: string | null;
};

export type AnalysisProgress = {
  total: number;
  waiting: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  inconclusive: number;
  items: AnalysisProgressItem[];
  generated_at: string;
};

export type Notification = {
  id: string;
  user_id: string;
  risk_workspace_id: string;
  notification_type: string;
  status: "UNREAD" | "READ";
  created_at: string;
  read_at: string | null;
  metadata_safe: Record<string, unknown>;
};

export type NotificationInbox = {
  items: Notification[];
  unread_count: number;
  next_cursor: string | null;
};
