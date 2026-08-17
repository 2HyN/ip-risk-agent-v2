import { useState } from "react";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { useResource } from "../shared/hooks/use-resource";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../shared/ui";

export function NotificationsPage() {
  const { api } = useSession();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const resource = useResource(
    () => api.notifications(unreadOnly),
    [api, unreadOnly],
  );
  async function markRead(id: string) {
    await api.markNotificationRead(id);
    resource.reload();
  }
  return (
    <main className="content">
      <PageHeader
        eyebrow="Personal inbox"
        title="Notifications"
        description={`${resource.data?.unread_count ?? 0} unread operational and risk updates.`}
        actions={
          <Button
            variant="secondary"
            onClick={() => setUnreadOnly((value) => !value)}
          >
            {unreadOnly ? "Show all" : "Unread only"}
          </Button>
        }
      />
      {resource.loading ? (
        <LoadingState label="Loading notifications" />
      ) : resource.error !== null ? (
        <ErrorState error={resource.error} retry={resource.reload} />
      ) : resource.data?.items.length === 0 ? (
        <EmptyState
          title={unreadOnly ? "You're all caught up" : "No notifications yet"}
          description="High risks, analysis failures, and source health updates will appear here."
        />
      ) : (
        <Card>
          <ul className="notification-list">
            {resource.data?.items.map((item) => (
              <li
                key={item.id}
                className={item.status === "UNREAD" ? "is-unread" : ""}
              >
                <span className="notification-mark" />
                <div>
                  <div className="card-row">
                    <strong>{humanize(item.notification_type)}</strong>
                    <Badge
                      tone={item.status === "UNREAD" ? "warning" : "neutral"}
                    >
                      {item.status}
                    </Badge>
                  </div>
                  <p>Workspace {item.risk_workspace_id}</p>
                  <time>{formatDate(item.created_at)}</time>
                </div>
                {item.status === "UNREAD" ? (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void markRead(item.id);
                    }}
                  >
                    Mark read
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </main>
  );
}
