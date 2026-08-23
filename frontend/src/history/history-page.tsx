import { useState } from "react";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { usePagedResource } from "../shared/hooks/use-paged-resource";
import { useResource } from "../shared/hooks/use-resource";
import type { HistoryEntry } from "../shared/api/types";
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

/** 로그에 딸린 안전 메타데이터 중 화면에 그대로 보여도 되는 짧은 값만 고른다. */
function metadataPairs(entry: HistoryEntry): Array<[string, string]> {
  return Object.entries(entry.metadata_safe)
    .filter(([, value]) =>
      ["string", "number", "boolean"].includes(typeof value),
    )
    .map(([key, value]) => [key, String(value)] as [string, string])
    .filter(([, value]) => value.length > 0 && value.length <= 120)
    .slice(0, 6);
}

export function HistoryPage() {
  const { api } = useSession();
  const { workspace, canViewAudit } = useWorkspace();
  const [kind, setKind] = useState<HistoryKind>("activity");
  const resource = usePagedResource(
    (cursor) => api.history(workspace.id, kind, cursor),
    [api, workspace.id, kind],
  );
  // 로그의 id 만으로는 사람이 사건을 되짚을 수 없다 — 어떤 소스의 어떤 파일인지를
  // 함께 보여 주려고 추적 목록을 한 번 읽어 id → 이름을 잇는다.
  const context = useResource(() => api.dataAccess(workspace.id), [api, workspace.id]);
  const artifactById = new Map(
    (context.data?.tracked_artifacts ?? []).map((item) => [item.artifact_id, item]),
  );
  const mountById = new Map(
    (context.data?.connected_sources ?? []).map((item) => [item.mount_id, item]),
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
            {resource.data?.items.map((entry) => {
              const artifact =
                entry.artifact_id === null
                  ? undefined
                  : artifactById.get(entry.artifact_id);
              const mount =
                entry.mount_id === null
                  ? undefined
                  : mountById.get(entry.mount_id);
              const pairs = metadataPairs(entry);
              return (
                <li key={entry.id}>
                  <span className="activity-icon" aria-hidden="true">
                    {entry.stream === "SOURCE_ACCESS" ? "↗" : "◇"}
                  </span>
                  <div>
                    <div className="card-row">
                      <strong>{humanize(entry.event_type)}</strong>
                      <Badge tone="neutral">{entry.stream}</Badge>
                    </div>
                    {artifact === undefined && mount === undefined ? null : (
                      <p className="activity-context">
                        {mount === undefined
                          ? null
                          : `${
                              mount.source_type === null
                                ? "Source"
                                : humanize(mount.source_type)
                            } · ${mount.alias}`}
                        {artifact === undefined
                          ? null
                          : `${mount === undefined ? "" : " · "}${artifact.display_name} (${artifact.logical_path})`}
                      </p>
                    )}
                    <p>
                      {entry.actor_type === "USER"
                        ? `User ${entry.actor_user_id ?? "unknown"}`
                        : "System"}
                      {mount !== undefined || entry.mount_id === null
                        ? ""
                        : ` · Mount ${entry.mount_id}`}
                      {artifact !== undefined || entry.artifact_id === null
                        ? ""
                        : ` · Artifact ${entry.artifact_id}`}
                      {entry.risk_id === null ? "" : ` · Risk ${entry.risk_id}`}
                    </p>
                    {pairs.length === 0 ? null : (
                      <p className="activity-metadata">
                        {pairs.map(([key, value]) => (
                          <span key={key} className="activity-metadata__pair">
                            <span className="activity-metadata__key">{key}</span>
                            {value}
                          </span>
                        ))}
                      </p>
                    )}
                    <time>{formatDate(entry.occurred_at)}</time>
                  </div>
                </li>
              );
            })}
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
