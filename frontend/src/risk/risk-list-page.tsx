import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
  Select,
  toneFor,
} from "../shared/ui";
import { useWorkspace } from "../workspace/workspace-context";

type Filters = {
  lifecycle_state: string;
  analysis_type: string;
  review_priority: string;
  review_disposition: string;
  mount_id: string;
  source_type: string;
};
const initialFilters: Filters = {
  lifecycle_state: "",
  analysis_type: "",
  review_priority: "",
  review_disposition: "",
  mount_id: "",
  source_type: "",
};

export function RiskListPage() {
  const { api } = useSession();
  const { workspace } = useWorkspace();
  const [filters, setFilters] = useState(initialFilters);
  const filterKey = JSON.stringify(filters);
  const resource = usePagedResource(
    (cursor) => api.risks(workspace.id, filters, cursor),
    [api, workspace.id, filterKey],
  );
  const mounts = usePagedResource(
    (cursor) => api.mounts(workspace.id, cursor),
    [api, workspace.id],
  );
  const hasFilters = useMemo(
    () => Object.values(filters).some(Boolean),
    [filters],
  );
  function set(name: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  return (
    <div className="content">
      <PageHeader
        eyebrow="Canonical risk register"
        title="Risks"
        description="Machine lifecycle and reviewer disposition remain separate, so analysis updates never overwrite human decisions."
      />
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
        <Select
          aria-label="Source provider"
          value={filters.source_type}
          onChange={(event) => set("source_type", event.target.value)}
        >
          <option value="">All providers</option>
          <option value="GOOGLE_DRIVE">Google Drive</option>
          <option value="GITHUB">GitHub</option>
          <option value="LOCAL">Local desktop</option>
        </Select>
        <Select
          aria-label="Source mount"
          value={filters.mount_id}
          onChange={(event) => set("mount_id", event.target.value)}
        >
          <option value="">All mounts</option>
          {mounts.data?.items.map((mount) => (
            <option key={mount.id} value={mount.id}>
              {mount.alias}
            </option>
          ))}
        </Select>
      </Card>
      {mounts.data?.next_cursor === null || mounts.data === null ? null : (
        <div className="pagination-actions">
          <Button
            variant="secondary"
            disabled={mounts.loadingMore}
            onClick={mounts.loadMore}
          >
            {mounts.loadingMore ? "Loading…" : "Load more source filters"}
          </Button>
        </div>
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
              ? "Adjust the filters to broaden this view."
              : "Authoritative analysis results will appear here when candidates are detected."
          }
        />
      ) : (
        <Card className="table-card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Risk</th>
                  <th>Artifact</th>
                  <th>Priority</th>
                  <th>Lifecycle</th>
                  <th>Review</th>
                  <th>Last seen</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {resource.data?.items.map((risk) => (
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
                      <strong>
                        {risk.artifact_display_name ?? risk.artifact_id}
                      </strong>
                      <small>
                        {risk.artifact_logical_path ?? "Canonical artifact"}
                      </small>
                    </td>
                    <td>
                      <Badge tone={toneFor(risk.review_priority)}>
                        {risk.review_priority}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={toneFor(risk.lifecycle_state)}>
                        {risk.lifecycle_state}
                      </Badge>
                    </td>
                    <td>{humanize(risk.review_disposition)}</td>
                    <td>{formatDate(risk.last_seen_at)}</td>
                    <td>
                      {risk.mount_alias ?? "—"}
                      <small>
                        {risk.source_type === null
                          ? ""
                          : humanize(risk.source_type)}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
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
  );
}
