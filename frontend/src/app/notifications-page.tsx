import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { usePagedResource } from "../shared/hooks/use-paged-resource";
import type { Notification } from "../shared/api/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
} from "../shared/ui";

/** 이 알림이 가리키는 화면. Risk 하나면 그 Risk, 파일 묶음이면 그 파일의 목록. */
function destinationFor(item: Notification): string {
  const base = `/w/${encodeURIComponent(item.risk_workspace_id)}`;
  const riskId = item.metadata_safe["risk_id"];
  const artifactId = item.metadata_safe["artifact_id"];
  const riskCount = item.metadata_safe["risk_count"];
  if (typeof artifactId === "string" && typeof riskCount === "number" && riskCount > 1) {
    return `${base}/risks?artifact_id=${encodeURIComponent(artifactId)}`;
  }
  if (typeof riskId === "string" && riskId.length > 0) {
    return `${base}/risks/${encodeURIComponent(riskId)}`;
  }
  if (typeof artifactId === "string" && artifactId.length > 0) {
    return `${base}/risks?artifact_id=${encodeURIComponent(artifactId)}`;
  }
  return base;
}

export function NotificationsPage() {
  const { api } = useSession();
  const navigate = useNavigate();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const resource = usePagedResource(
    (cursor) => api.notifications(unreadOnly, cursor),
    [api, unreadOnly],
  );
  async function markRead(id: string) {
    await api.markNotificationRead(id);
    resource.reload();
  }
  function open(item: Notification): void {
    // 읽음 처리는 이동을 막지 않는다 — 실패해도 사용자는 목적지로 간다.
    if (item.status === "UNREAD") void api.markNotificationRead(item.id);
    navigate(destinationFor(item));
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
            {resource.data?.items.map((item) => {
              const displayName = item.metadata_safe["display_name"];
              const riskCount = item.metadata_safe["risk_count"];
              return (
                <li
                  key={item.id}
                  className={item.status === "UNREAD" ? "is-unread" : ""}
                >
                  <span className="notification-mark" />
                  {/* 알림은 곧 입구다 — 누르면 그 Risk(또는 그 파일의 목록)로 간다. */}
                  <button
                    type="button"
                    className="notification-body"
                    onClick={() => open(item)}
                  >
                    <div className="card-row">
                      <strong>{humanize(item.notification_type)}</strong>
                      <Badge
                        tone={item.status === "UNREAD" ? "warning" : "neutral"}
                      >
                        {item.status}
                      </Badge>
                    </div>
                    <p>
                      {typeof displayName === "string" && displayName.length > 0
                        ? `${displayName}${
                            typeof riskCount === "number" && riskCount > 1
                              ? ` · 검토할 위험 ${riskCount}건`
                              : ""
                          }`
                        : `Workspace ${item.risk_workspace_id}`}
                    </p>
                    <time>{formatDate(item.created_at)}</time>
                  </button>
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
              );
            })}
          </ul>
        </Card>
      )}
      {resource.data?.next_cursor === null || resource.data === null ? null : (
        <div className="pagination-actions">
          <Button
            variant="secondary"
            disabled={resource.loadingMore}
            onClick={resource.loadMore}
          >
            {resource.loadingMore ? "Loading…" : "Load more notifications"}
          </Button>
        </div>
      )}
    </main>
  );
}
