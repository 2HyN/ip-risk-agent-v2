import { useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize, shortRevision } from "../shared/format";
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

type HistoryKind = "activity" | "risk-events" | "audit" | "source-access";

// 사람이 읽어서 뜻이 없는 조각. 요약·파일 이름 등 본문이 된 것도 칩으로는
// 다시 적지 않는다. 내보내기 JSON 에는 전부 그대로 남는다.
const HIDDEN_METADATA_KEYS = new Set([
  "analysis_job_id",
  "evidence_refs",
  "artifact_id",
  "risk_id",
  "display_name",
  "provider_request_id",
  "summary",
  "analysis_type",
]);

/** 해시로 된 기계 식별자인가 — 화면에서는 소음이다. */
function looksLikeMachineId(value: string): boolean {
  return /^[a-z-]+:v\d+:[0-9a-f]{16,}$/iu.test(value) || /^[0-9a-f]{32,}$/iu.test(value);
}

/** 로그에 딸린 안전 메타데이터 중 사람이 읽을 수 있는 짧은 값만 고른다. */
function metadataPairs(entry: HistoryEntry): Array<[string, string]> {
  return Object.entries(entry.metadata_safe)
    .filter(([key]) => !HIDDEN_METADATA_KEYS.has(key))
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
    .map(
      ([key, value]) =>
        [key, key === "revision" ? shortRevision(String(value)) : String(value)] as [
          string,
          string,
        ],
    )
    .filter(([, value]) => value.length > 0 && value.length <= 120 && !looksLikeMachineId(value))
    .slice(0, 6);
}

function metadataText(entry: HistoryEntry, key: string): string | null {
  const value = entry.metadata_safe[key];
  return typeof value === "string" && value.length > 0 ? value : null;
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
  // 행위자도 id 로만 오면 사람이 못 알아본다 — 멤버 목록으로 이름을 되짚는다.
  const members = useResource(() => api.members(workspace.id), [api, workspace.id]);
  const artifactById = new Map(
    (context.data?.tracked_artifacts ?? []).map((item) => [item.artifact_id, item]),
  );
  const mountById = new Map(
    (context.data?.connected_sources ?? []).map((item) => [item.mount_id, item]),
  );
  const memberById = new Map(
    (members.data?.items ?? []).map((item) => [item.user_id, item]),
  );
  function actorLabel(userId: string | null): string {
    if (userId === null) return "unknown user";
    const member = memberById.get(userId);
    return member?.user_display_name ?? member?.user_email ?? userId;
  }
  return (
    <div className="content">
      <PageHeader
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
          aria-selected={kind === "risk-events"}
          onClick={() => setKind("risk-events")}
        >
          Risk
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
              const analysisType = metadataText(entry, "analysis_type");
              const summary = metadataText(entry, "summary");
              const title = analysisType === null
                ? humanize(entry.event_type)
                : `${humanize(analysisType)} risk ${humanize(entry.event_type).toLowerCase()}`;
              return (
                <li key={entry.id}>
                  <span className="activity-icon" aria-hidden="true">
                    {entry.stream === "SOURCE_ACCESS" ? "↗" : "◇"}
                  </span>
                  <div>
                    <div className="card-row">
                      {entry.risk_id === null ? (
                        <strong>{title}</strong>
                      ) : (
                        <Link
                          className="risk-link"
                          to={`/w/${workspace.id}/risks/${encodeURIComponent(entry.risk_id)}`}
                        >
                          <strong>{title}</strong>
                        </Link>
                      )}
                      <Badge tone="neutral">{entry.stream}</Badge>
                    </div>
                    {summary === null ? null : <p>“{summary}”</p>}
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
                          : `${mount === undefined ? "" : " · "}${artifact.logical_path}`}
                      </p>
                    )}
                    <p>
                      {entry.actor_type === "USER"
                        ? actorLabel(entry.actor_user_id)
                        : "System"}
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
