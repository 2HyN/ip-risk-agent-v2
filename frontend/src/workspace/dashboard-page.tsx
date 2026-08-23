import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { useResource } from "../shared/hooks/use-resource";
import { useAnalysisProgress } from "../shared/hooks/use-analysis-progress";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../shared/ui";
import { useWorkspace } from "./workspace-context";

export function DashboardPage() {
  const { api } = useSession();
  const { workspace, role } = useWorkspace();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<Error | null>(null);
  const resource = useResource(
    () => api.dashboard(workspace.id),
    [api, workspace.id],
  );

  async function deleteWorkspace(): Promise<void> {
    // 지우면 이 workspace 의 마운트·Risk·이력이 모두 정리 대상이 된다.
    // 이름을 되묻는 확인 한 번으로는 부족할 수 있지만, confirm 없이 지우는
    // 것보다는 낫다 — 버튼도 OWNER 에게만 보인다.
    const confirmed = window.confirm(
      `"${workspace.name}" workspace를 삭제할까요?\n` +
        "마운트, Risk, 이력이 모두 삭제 절차에 들어가며 되돌릴 수 없습니다.",
    );
    if (!confirmed) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteWorkspace(workspace.id);
      navigate("/");
    } catch (reason) {
      setDeleteError(
        reason instanceof Error ? reason : new Error("Workspace를 삭제하지 못했습니다."),
      );
      setDeleting(false);
    }
  }
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
          <div className="button-row">
            <Link
              className="button button--primary"
              to={`/w/${workspace.id}/risks`}
            >
              Review risks
            </Link>
            {role === "OWNER" ? (
              <Button
                variant="danger"
                disabled={deleting}
                onClick={() => void deleteWorkspace()}
              >
                {deleting ? "Deleting…" : "Delete workspace"}
              </Button>
            ) : null}
          </div>
        }
      />
      {deleteError === null ? null : <ErrorState error={deleteError} />}
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
        <AnalysisMonitorCard workspaceId={workspace.id} />
      </div>
    </div>
  );
}

/**
 * 작업 현황 — 지금 몇 개가 검사 중이고 몇 개가 끝났는가.
 *
 * 분석은 worker 에서 돌므로 이 카드가 주기적으로 묻는다. 문서 단위로 센다 —
 * 실행 기록을 세면 파일을 고칠 때마다 진행률이 뒤로 간다.
 */
export function AnalysisMonitorCard({ workspaceId }: { workspaceId: string }) {
  const { api } = useSession();
  const load = useCallback(
    () => api.analysesProgress(workspaceId),
    [api, workspaceId],
  );
  const progress = useAnalysisProgress(load);
  if (progress === null) {
    return (
      <Card>
        <p className="eyebrow">Analysis monitor</p>
        <h2>작업 현황</h2>
        <LoadingState label="Checking analysis activity" />
      </Card>
    );
  }
  const done = progress.succeeded + progress.inconclusive + progress.failed;
  const active = progress.queued + progress.running;
  const percent =
    progress.total === 0 ? 100 : Math.round((done / progress.total) * 100);
  return (
    <Card>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Analysis monitor</p>
          <h2>작업 현황</h2>
        </div>
        <Badge tone={progress.failed > 0 ? "warning" : active > 0 ? "info" : "success"}>
          {active > 0 ? `${active} in progress` : "Idle"}
        </Badge>
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Analysis progress"
      >
        <div className="progress__bar" style={{ width: `${percent}%` }} />
      </div>
      <p className="progress__caption">
        {progress.total === 0
          ? "추적 중인 파일이 아직 없습니다."
          : `${done} / ${progress.total} 문서 검사 완료 (${percent}%)`}
      </p>
      <div className="health-bars">
        <Health label="Running" value={progress.running} tone="healthy" />
        <Health label="Queued" value={progress.queued} tone="muted" />
        <Health label="Waiting" value={progress.waiting} tone="muted" />
        <Health label="Failed" value={progress.failed} tone="danger" />
      </div>
      {progress.items.length === 0 ? null : (
        <ul className="progress-items">
          {progress.items.slice(0, 5).map((item) => (
            <li key={item.artifact_id}>
              <span className="progress-items__name">{item.display_name}</span>
              <Badge tone={item.status === "FAILED" ? "danger" : "info"}>
                {item.status}
              </Badge>
            </li>
          ))}
          {progress.items.length > 5 ? (
            <li className="progress-items__more">
              +{progress.items.length - 5} more
            </li>
          ) : null}
        </ul>
      )}
    </Card>
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
