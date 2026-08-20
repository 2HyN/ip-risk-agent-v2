import { useState } from "react";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { usePagedResource } from "../shared/hooks/use-paged-resource";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../shared/ui";
import { useWorkspace } from "../workspace/workspace-context";

type HistoryKind = "activity" | "audit" | "source-access";

export function HistoryPage() {
  const { api } = useSession();
  const { workspace, canViewAudit } = useWorkspace();
  const [kind, setKind] = useState<HistoryKind>("activity");
  const resource = usePagedResource(
    (cursor) => api.history(workspace.id, kind, cursor),
    [api, workspace.id, kind],
  );
  return (
    <div className="content">
      <PageHeader
        eyebrow="Operational record"
        title="Activity & audit"
        description="Content-free workspace, risk, and source access history."
        actions={
          canViewAudit ? (
            <a
              className="button button--secondary"
              href={api.exportAuditUrl(workspace.id)}
              download
            >
              Export safe audit JSON
            </a>
          ) : undefined
        }
      />
      <div className="tabs" role="tablist" aria-label="History stream">
        <button
          role="tab"
          aria-selected={kind === "activity"}
          onClick={() => setKind("activity")}
        >
          All activity
        </button>
        <button
          role="tab"
          aria-selected={kind === "audit"}
          onClick={() => setKind("audit")}
        >
          Audit
        </button>
        <button
          role="tab"
          aria-selected={kind === "source-access"}
          onClick={() => setKind("source-access")}
        >
          Source access
        </button>
      </div>
      {resource.loading ? (
        <LoadingState label="Loading history" />
      ) : resource.error !== null ? (
        <ErrorState error={resource.error} retry={resource.reload} />
      ) : resource.data?.items.length === 0 ? (
        <EmptyState
          title="No history in this stream"
          description="Canonical events will appear as workspace activity occurs."
        />
      ) : (
        <Card>
          <ol className="activity-list">
            {resource.data?.items.map((entry) => (
              <li key={entry.id}>
                <span className="activity-icon" aria-hidden="true">
                  {entry.stream === "SOURCE_ACCESS" ? "↗" : "◇"}
                </span>
                <div>
                  <div className="card-row">
                    <strong>{humanize(entry.event_type)}</strong>
                    <Badge tone="neutral">{entry.stream}</Badge>
                  </div>
                  <p>
                    {entry.actor_type === "USER"
                      ? `User ${entry.actor_user_id ?? "unknown"}`
                      : "System"}
                    {entry.mount_id === null
                      ? ""
                      : ` · Mount ${entry.mount_id}`}
                  </p>
                  <time>{formatDate(entry.occurred_at)}</time>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}
      {resource.data?.next_cursor === null || resource.data === null ? null : (
        <div className="pagination-actions">
          <Button
            variant="secondary"
            disabled={resource.loadingMore}
            onClick={resource.loadMore}
          >
            {resource.loadingMore ? "Loading…" : "Load more history"}
          </Button>
        </div>
      )}
    </div>
  );
}
