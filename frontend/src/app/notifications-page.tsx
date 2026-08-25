import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { usePagedResource } from "../shared/hooks/use-paged-resource";
import type { Notification } from "../shared/api/types";
import {
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

/** 알림 종류 → 점 색. Risk 는 위험색, 분석 실패는 경고색, 소스 상태는 청색. */
function markClassFor(type: string): string {
  if (type.startsWith("RISK_")) return "notification-mark notification-mark--risk";
  if (type.startsWith("ANALYSIS_"))
    return "notification-mark notification-mark--analysis";
  if (type.startsWith("MOUNT_") || type.startsWith("SOURCE_"))
    return "notification-mark notification-mark--source";
  return "notification-mark";
}

export function NotificationsPage() {
  const { api } = useSession();
  const navigate = useNavigate();
  // 기본은 안 읽은 것만 — 받은 편지함의 용건은 "아직 처리 안 한 것" 이다.
  const [unreadOnly, setUnreadOnly] = useState(true);
  const [bulkBusy, setBulkBusy] = useState(false);
  const resource = usePagedResource(
    (cursor) => api.notifications(unreadOnly, cursor),
    [api, unreadOnly],
  );
  async function dismiss(id: string) {
    await api.markNotificationRead(id);
    resource.reload();
  }
  /** 지금 화면에 로드된 안 읽은 알림 전부를 한 번에 읽음 처리. */
  async function dismissAll() {
    const unread =
      resource.data?.items.filter((item) => item.status === "UNREAD") ?? [];
    if (unread.length === 0) return;
    setBulkBusy(true);
    try {
      await Promise.all(unread.map((item) => api.markNotificationRead(item.id)));
    } finally {
      setBulkBusy(false);
      resource.reload();
    }
  }
  function open(item: Notification): void {
    // 읽음 처리는 이동을 막지 않는다 — 실패해도 사용자는 목적지로 간다.
    if (item.status === "UNREAD") void api.markNotificationRead(item.id);
    navigate(destinationFor(item));
  }
  const unreadShown =
    resource.data?.items.filter((item) => item.status === "UNREAD").length ?? 0;
  return (
    <main className="content">
      <PageHeader
        title="Notifications"
        description={`${resource.data?.unread_count ?? 0} unread operational and risk updates.`}
        actions={
          <div className="button-row">
            {unreadShown > 1 ? (
              <Button
                variant="secondary"
                disabled={bulkBusy}
                onClick={() => void dismissAll()}
              >
                {bulkBusy ? "Dismissing…" : `Dismiss all (${unreadShown})`}
              </Button>
            ) : null}
            <Button
              variant="secondary"
              onClick={() => setUnreadOnly((value) => !value)}
            >
              {unreadOnly ? "Show all" : "Unread only"}
            </Button>
          </div>
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
                  <span className={markClassFor(item.notification_type)} />
                  {/* 알림은 곧 입구다 — 누르면 그 Risk(또는 그 파일의 목록)로 간다. */}
                  <button
                    type="button"
                    className="notification-body"
                    onClick={() => open(item)}
                  >
                    <div className="card-row">
                      <strong>{humanize(item.notification_type)}</strong>
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
                  {/* 읽음 여부와 무관하게 같은 폭을 차지한다 — 점·본문 위치 고정. */}
                  <span className="notification-action">
                    {item.status === "UNREAD" ? (
                      <Button
                        variant="ghost"
                        onClick={() => {
                          void dismiss(item.id);
                        }}
                      >
                        Dismiss
                      </Button>
                    ) : null}
                  </span>
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
