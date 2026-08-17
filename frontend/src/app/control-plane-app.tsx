import {
  BrowserRouter,
  HashRouter,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";
import { SessionProvider } from "../auth/session";
import { LoginPage } from "../auth/login-page";
import { WorkspaceListPage } from "../workspace/workspace-list-page";
import { DashboardPage } from "../workspace/dashboard-page";
import { MembersPage } from "../workspace/members-page";
import { RiskListPage } from "../risk/risk-list-page";
import { RiskDetailPage } from "../risk/risk-detail-page";
import { RiskTimelinePage } from "../risk/risk-timeline-page";
import { HistoryPage } from "../history/history-page";
import { SecurityPage } from "../security/security-page";
import { AuthGuard } from "./auth-guard";
import { AppShell, WorkspaceLayout } from "./app-shell";
import { NotificationsPage } from "./notifications-page";
import { SourceSlotPage } from "./source-slot-page";
import { IntegrationContext } from "./integration-context";
import type { ControlPlaneIntegration } from "./integration";
import "../shared/styles.css";

export type ControlPlaneAppProps = {
  apiBaseUrl?: string;
  integration?: ControlPlaneIntegration;
  router?: "browser" | "hash";
};

export function ControlPlaneApp({
  apiBaseUrl = "",
  integration = {},
  router = "browser",
}: ControlPlaneAppProps) {
  const Router = router === "hash" ? HashRouter : BrowserRouter;
  return (
    <SessionProvider apiBaseUrl={apiBaseUrl}>
      <IntegrationContext.Provider value={integration}>
        <Router>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<AuthGuard />}>
              <Route element={<AppShell />}>
                <Route index element={<WorkspaceListPage />} />
                <Route path="notifications" element={<NotificationsPage />} />
                <Route path="w/:workspaceId" element={<WorkspaceLayout />}>
                  <Route index element={<DashboardPage />} />
                  <Route path="risks" element={<RiskListPage />} />
                  <Route path="risks/:riskId" element={<RiskDetailPage />} />
                  <Route
                    path="risks/:riskId/timeline"
                    element={<RiskTimelinePage />}
                  />
                  <Route path="members" element={<MembersPage />} />
                  <Route path="history" element={<HistoryPage />} />
                  <Route path="security" element={<SecurityPage />} />
                  <Route path="sources/*" element={<SourceSlotPage />} />
                </Route>
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </IntegrationContext.Provider>
    </SessionProvider>
  );
}
