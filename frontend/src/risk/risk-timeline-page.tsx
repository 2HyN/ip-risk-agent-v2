import { Link, useParams } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { useResource } from "../shared/hooks/use-resource";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../shared/ui";
import { useWorkspace } from "../workspace/workspace-context";

export function RiskTimelinePage() {
  const { riskId = "" } = useParams();
  const { api } = useSession();
  const { workspace } = useWorkspace();
  const resource = useResource(
    () => api.timeline(workspace.id, riskId),
    [api, workspace.id, riskId],
  );
  if (resource.loading) return <LoadingState label="Loading timeline" />;
  if (resource.error !== null)
    return <ErrorState error={resource.error} retry={resource.reload} />;
  if (resource.data === null) return null;
  return (
    <div className="content">
      <PageHeader
        title="Risk timeline"
        description={resource.data.risk.summary}
        actions={
          <Link
            className="button button--secondary"
            to={`/w/${workspace.id}/risks/${riskId}`}
          >
            Back to risk
          </Link>
        }
      />
      {resource.data.entries.length === 0 ? (
        <EmptyState
          title="No events yet"
          description="Risk lifecycle and review events will be shown here."
        />
      ) : (
        <Card>
          <ol className="timeline">
            {resource.data.entries.map((entry) => (
              <li key={entry.id}>
                <span className="timeline__dot" />
                <div>
                  <div className="card-row">
                    <Badge tone="info">{humanize(entry.event_type)}</Badge>
                    <time>{formatDate(entry.occurred_at)}</time>
                  </div>
                  <p>
                    {entry.actor_type === "USER"
                      ? `Changed by ${entry.actor_user_id ?? "a user"}`
                      : "Recorded by the system"}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
