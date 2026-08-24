import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  PriorityBadge,
  Select,
  toneFor,
} from "../shared/ui";
import type { Risk } from "../shared/api/types";
import { useWorkspace } from "../workspace/workspace-context";

type Filters = {
  lifecycle_state: string;
  analysis_type: string;
  review_priority: string;
  review_disposition: string;
  mount_id: string;
};
type ArtifactGroup = {
  artifactId: string;
  displayName: string;
  logicalPath: string | null;
  openCount: number;
  risks: Risk[];
};

/**
 * 한 파일에서 나온 Risk 를 한 묶음으로 (3-C).
 *
 * Risk 는 파일에서 나온다 — 파일 하나에 특허 · 라이선스 Risk 가 여럿 걸리는 것이
 * 보통이라, 평평한 목록은 같은 파일이 몇 번이고 흩어져 나온다. 묶음 순서는 받은
 * 순서(우선순위·최근성은 서버 정렬)를 따르되 같은 파일은 처음 나온 자리에 모은다.
 *
 * 소스 구분은 왼쪽 레일이 맡으므로 카드에는 경로만 적는다 — 경로의 첫 칸이
 * 이미 소스 폴더 이름이다.
 */
function groupByArtifact(risks: Risk[]): ArtifactGroup[] {
  const groups = new Map<string, ArtifactGroup>();
  for (const risk of risks) {
    let group = groups.get(risk.artifact_id);
    if (group === undefined) {
      group = {
        artifactId: risk.artifact_id,
        displayName: risk.artifact_display_name ?? risk.artifact_id,
        logicalPath: risk.artifact_logical_path,
        openCount: 0,
        risks: [],
      };
      groups.set(risk.artifact_id, group);
    }
    group.risks.push(risk);
    if (
      risk.lifecycle_state !== "RESOLVED" &&
      risk.review_disposition === "UNREVIEWED"
    ) {
      group.openCount += 1;
    }
  }
  return [...groups.values()];
}

const initialFilters: Filters = {
  lifecycle_state: "",
  analysis_type: "",
  review_priority: "",
  review_disposition: "",
  mount_id: "",
};

export function RiskListPage() {
  const { api } = useSession();
  const { workspace } = useWorkspace();
  const [search, setSearch] = useSearchParams();
  // Files 에서 파일을 눌러 넘어온 경우 — 그 파일의 Risk 만 본다.
  const artifactId = search.get("artifact_id") ?? "";
  const [filters, setFilters] = useState(initialFilters);
  const query = useMemo(
    () => ({
      ...filters,
      ...(artifactId === "" ? {} : { artifact_id: artifactId }),
    }),
    [filters, artifactId],
  );
  const queryKey = JSON.stringify(query);
  const resource = usePagedResource(
    (cursor) => api.risks(workspace.id, query, cursor),
    [api, workspace.id, queryKey],
  );
  const mounts = usePagedResource(
    (cursor) => api.mounts(workspace.id, cursor),
    [api, workspace.id],
  );
  const hasFilters = useMemo(
    () => Object.values(filters).some(Boolean) || artifactId !== "",
    [filters, artifactId],
  );
  function set(name: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  const groups = groupByArtifact(resource.data?.items ?? []);

  return (
    <div className="content content--wide">
      <PageHeader
        eyebrow="Canonical risk register"
        title="Review"
        description="한 파일에서 나온 Risk를 모아서 봅니다. Machine lifecycle과 reviewer disposition은 분리되어 있어 분석 갱신이 사람의 판단을 덮지 않습니다."
      />
      <div className="review-layout">
        <aside className="review-rail" aria-label="Source filter">
          <p className="eyebrow">Sources</p>
          <button
            type="button"
            className={filters.mount_id === "" ? "is-active" : ""}
            onClick={() => set("mount_id", "")}
          >
            All sources
          </button>
          {mounts.data?.items.map((mount) => (
            <button
              key={mount.id}
              type="button"
              className={filters.mount_id === mount.id ? "is-active" : ""}
              onClick={() => set("mount_id", mount.id)}
            >
              {mount.alias}
            </button>
          ))}
          {mounts.data?.next_cursor === null || mounts.data === null ? null : (
            <Button
              variant="ghost"
              disabled={mounts.loadingMore}
              onClick={mounts.loadMore}
            >
              {mounts.loadingMore ? "Loading…" : "More sources"}
            </Button>
          )}
        </aside>
        <div className="review-main">
          <Card className="filter-bar" aria-label="Risk filters">
            <Select
              aria-label="Lifecycle"
              value={filters.lifecycle_state}
              onChange={(event) => set("lifecycle_state", event.target.value)}
            >
              <option value="">All lifecycle states</option>
              <option value="NEW">New</option>
              <option value="EXISTING">Existing</option>
              <option value="RESOLVED">Resolved</option>
            </Select>
            <Select
              aria-label="Analysis type"
              value={filters.analysis_type}
              onChange={(event) => set("analysis_type", event.target.value)}
            >
              <option value="">Patent &amp; license</option>
              <option value="PATENT">Patent</option>
              <option value="LICENSE">License</option>
            </Select>
            <Select
              aria-label="Priority"
              value={filters.review_priority}
              onChange={(event) => set("review_priority", event.target.value)}
            >
              <option value="">All priorities</option>
              <option value="HIGH">High</option>
              <option value="INDETERMINATE">Needs a look</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </Select>
            <Select
              aria-label="Review disposition"
              value={filters.review_disposition}
              onChange={(event) => set("review_disposition", event.target.value)}
            >
              <option value="">All review states</option>
              <option value="UNREVIEWED">Unreviewed</option>
              <option value="MONITORING">Monitoring</option>
              <option value="ACCEPTED_RISK">Accepted risk</option>
              <option value="EXCLUDED">Excluded</option>
            </Select>
          </Card>
          {artifactId === "" ? null : (
            <p className="filter-chip" role="status">
              <span>
                파일 하나의 Risk만 보는 중
                {groups[0] === undefined ? "" : ` — ${groups[0].displayName}`}
              </span>
              <Button
                variant="ghost"
                onClick={() => setSearch({}, { replace: true })}
              >
                전체 보기 ✕
              </Button>
            </p>
          )}
          {resource.loading ? (
            <LoadingState label="Loading risks" />
          ) : resource.error !== null ? (
            <ErrorState error={resource.error} retry={resource.reload} />
          ) : resource.data?.items.length === 0 ? (
            <EmptyState
              title={hasFilters ? "No matching risks" : "No risks detected"}
              description={
                hasFilters
                  ? "이 조건에 맞는 Risk가 없습니다. 필터를 넓히거나 전체 보기로 돌아가세요."
                  : "Authoritative analysis results will appear here when candidates are detected."
              }
            />
          ) : (
            <div className="review-groups">
              {groups.map((group) => (
                <Card key={group.artifactId} className="review-group">
                  <div className="review-group__head">
                    <div>
                      <h2>
                        <span className="explorer-icon" aria-hidden="true">📄</span>
                        {group.displayName}
                      </h2>
                      <p className="review-group__path">
                        {group.logicalPath ?? "Canonical artifact"}
                      </p>
                    </div>
                    <Badge tone={group.openCount > 0 ? "warning" : "success"}>
                      {group.openCount > 0
                        ? `검토 대기 ${group.openCount}`
                        : "모두 검토됨"}
                    </Badge>
                  </div>
                  <div className="table-wrap">
                    <table className="review-table">
                      <thead>
                        <tr>
                          <th>Risk</th>
                          <th>Priority</th>
                          <th>Lifecycle</th>
                          <th>Review</th>
                          <th>Last seen</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.risks.map((risk) => (
                          <tr key={risk.id}>
                            <td>
                              <Link
                                className="risk-link"
                                to={`/w/${workspace.id}/risks/${risk.id}`}
                              >
                                <Badge tone="info">{risk.analysis_type}</Badge>
                                <strong>{risk.summary}</strong>
                              </Link>
                            </td>
                            <td>
                              <PriorityBadge value={risk.review_priority} />
                            </td>
                            <td>
                              <Badge tone={toneFor(risk.lifecycle_state)}>
                                {risk.lifecycle_state}
                              </Badge>
                            </td>
                            <td>{humanize(risk.review_disposition)}</td>
                            <td>{formatDate(risk.last_seen_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              ))}
            </div>
          )}
          {resource.data?.next_cursor === null || resource.data === null ? null : (
            <div className="pagination-actions">
              <Button
                variant="secondary"
                disabled={resource.loadingMore}
                onClick={resource.loadMore}
              >
                {resource.loadingMore ? "Loading…" : "Load more risks"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
