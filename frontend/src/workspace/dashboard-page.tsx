import { Link } from "react-router-dom";
import { useSession } from "../auth/session";
import { useResource } from "../shared/hooks/use-resource";
import {
  Badge,
  Card,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../shared/ui";
import { useWorkspace } from "./workspace-context";

export function DashboardPage() {
  const { api } = useSession();
  const { workspace } = useWorkspace();
  const resource = useResource(
    () => api.dashboard(workspace.id),
    [api, workspace.id],
  );
  if (resource.loading)
    return <LoadingState label="Calculating workspace status" />;
  if (resource.error !== null)
    return <ErrorState error={resource.error} retry={resource.reload} />;
  const dashboard = resource.data;
  if (dashboard === null) return null;
  const metrics = [
    ["New risks", dashboard.new_risks, "Needs first review"],
    ["Monitoring", dashboard.monitoring_risks, "Under active observation"],
    ["Resolved recently", dashboard.resolved_recently, "Last 30 days"],
    [
      "Analysis failed",
      dashboard.analysis_failed,
      "Requires operational attention",
    ],
  ] as const;
  return (
    <div className="content">
      <PageHeader
        eyebrow="Workspace overview"
        title={workspace.name}
        description={
          workspace.description ??
          "Canonical risk, analysis, and source health at a glance."
        }
        actions={
          <Link
            className="button button--primary"
            to={`/w/${workspace.id}/risks`}
          >
            Review risks
          </Link>
        }
      />
      <div className="metric-grid">
        {metrics.map(([label, value, note]) => (
          <Card key={label} className="metric">
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </Card>
        ))}
      </div>
      <div className="dashboard-grid">
        <Card>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Connected source health</p>
              <h2>Collection readiness</h2>
            </div>
            <Badge
              tone={
                dashboard.source_health.action_required +
                  dashboard.source_health.offline >
                0
                  ? "warning"
                  : "success"
              }
            >
              {dashboard.source_health.active} active
            </Badge>
          </div>
          <div className="health-bars">
            <Health
              label="Active"
              value={dashboard.source_health.active}
              tone="healthy"
            />
            <Health
              label="Action required"
              value={dashboard.source_health.action_required}
              tone="warning"
            />
            <Health
              label="Offline"
              value={dashboard.source_health.offline}
              tone="danger"
            />
            <Health
              label="Disabled"
              value={dashboard.source_health.disabled}
              tone="muted"
            />
          </div>
          <Link className="text-link" to={`/w/${workspace.id}/security`}>
            View source and data access details →
          </Link>
        </Card>
        <Card className="assurance-card">
          <p className="eyebrow">Protection posture</p>
          <h2>Source stays at the source</h2>
          <p>
            The Control Plane stores approved analysis artifacts and minimal
            evidence—not raw source snapshots. Original files open through
            provider or owning-device authorization.
          </p>
          <ul className="check-list">
            <li>Global ignore policy applied before analysis</li>
            <li>Secret filtering and minimization enabled</li>
            <li>Reference knowledge only for external RAG</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

function Health({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="health-row">
      <span>
        <i className={`health-dot health-dot--${tone}`} />
        {label}
      </span>
      <strong>{value}</strong>
    </div>
  );
}
