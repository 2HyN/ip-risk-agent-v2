import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ControlPlaneApp } from "../app/control-plane-app";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const user = { id: "user-1", email: "owner@example.com", display_name: "Owner", avatar_url: null, csrf_token: "csrf-token" };
const workspace = { id: "vws-1", name: "Counsel", description: "Product portfolio", owner_user_id: "user-1", security_policy_version: "security-v1", retention_policy_version: "balanced-v1", created_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z", status: "ACTIVE" };
const membership = { id: "member-1", risk_workspace_id: "vws-1", user_id: "user-1", role: "OWNER", status: "ACTIVE", invited_by: "user-1", created_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z" };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = ""; });

describe("ControlPlaneApp", () => {
  it("shows the Google login boundary when no application session exists", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "AUTHENTICATION_REQUIRED", message: "Authentication is required" }, 401)));
    render(<ControlPlaneApp router="hash" />);
    expect(await screen.findByRole("heading", { name: /know what changed/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeEnabled();
  });

  it("renders the Agent 2 source slot without owning source UI", async () => {
    window.location.hash = "#/w/vws-1/sources";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return json(user);
      if (path.endsWith("/workspaces/vws-1/membership")) return json(membership);
      if (path.endsWith("/workspaces/vws-1")) return json(workspace);
      return json({ code: "NOT_FOUND", message: "Not found" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <section><h1>Injected provider sources</h1></section> }} />);
    expect(await screen.findByRole("heading", { name: "Injected provider sources" })).toBeInTheDocument();
  });

  it("delegates Open Original as an opaque callback and renders no source preview", async () => {
    window.location.hash = "#/w/vws-1/risks/risk-1";
    const openOriginal = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return json(user);
      if (path.endsWith("/workspaces/vws-1/membership")) return json(membership);
      if (path.endsWith("/workspaces/vws-1/risks/risk-1")) return json({ risk: { id: "risk-1", risk_workspace_id: "vws-1", artifact_id: "artifact-1", analysis_type: "PATENT", lifecycle_state: "NEW", review_disposition: "UNREVIEWED", review_priority: "HIGH", summary: "Potential claim overlap", first_seen_at: "2026-08-17T00:00:00Z", last_seen_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z", resolved_at: null, review_version: 0, latest_analysis_job_id: "job-1", latest_evidence_revision: "rev-1", artifact_display_name: "invention.md", artifact_logical_path: "/design/invention.md", mount_id: "mount-1", mount_alias: "Design", source_type: "GITHUB" }, evidence: [], open_original: { action: "SOURCE_OPEN_ORIGINAL", artifact_id: "artifact-1" } });
      if (path.endsWith("/workspaces/vws-1")) return json(workspace);
      return json({ code: "NOT_FOUND", message: "Not found" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ openOriginal }} />);
    await userEvent.click(await screen.findByRole("button", { name: /open on github/i }));
    expect(openOriginal).toHaveBeenCalledWith({ workspaceId: "vws-1", artifactId: "artifact-1", action: "SOURCE_OPEN_ORIGINAL", sourceType: "GITHUB" });
    // 원문은 절대 그리지 않는다 — 남긴 발췌가 없으면 빈 상태만 보인다.
    expect(screen.getByText("No retained excerpt")).toBeInTheDocument();
  });

  it.each([
    ["OWNER", true],
    ["SOURCE_MANAGER", false],
    ["RISK_REVIEWER", false],
    ["VIEWER", false],
  ] as const)("keeps %s navigation aligned with API capabilities", async (role, ownerActions) => {
    window.location.hash = "#/w/vws-1";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return json(user);
      if (path.endsWith("/workspaces/vws-1/membership")) return json({ ...membership, role });
      if (path.endsWith("/workspaces/vws-1/dashboard")) return json({ new_risks: 0, monitoring_risks: 0, resolved_recently: 0, analysis_failed: 0, source_health: { active: 0, action_required: 0, offline: 0, disabled: 0 } });
      if (path.endsWith("/workspaces/vws-1")) return json(workspace);
      return json({ code: "NOT_FOUND", message: "Not found" }, 404);
    }));
    render(<ControlPlaneApp router="hash" />);
    expect(await screen.findByRole("heading", { name: "Counsel" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /members & roles/i }) !== null).toBe(ownerActions);
    expect(screen.queryByRole("link", { name: /activity & audit/i }) !== null).toBe(ownerActions);
    expect(screen.getByRole("link", { name: /security & data/i })).toBeInTheDocument();
    // 왼쪽 탭 — Files(구 Sources) · Review(구 Risks) 순서의 새 이름.
    expect(screen.getByRole("link", { name: /^files$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^review$/i })).toBeInTheDocument();
  });

  it("redirects a direct audit route when the membership cannot view audit", async () => {
    window.location.hash = "#/w/vws-1/history";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return json(user);
      if (path.endsWith("/workspaces/vws-1/membership")) return json({ ...membership, role: "VIEWER" });
      if (path.endsWith("/workspaces/vws-1/dashboard")) return json({ new_risks: 0, monitoring_risks: 0, resolved_recently: 0, analysis_failed: 0, source_health: { active: 0, action_required: 0, offline: 0, disabled: 0 } });
      if (path.endsWith("/workspaces/vws-1")) return json(workspace);
      return json({ code: "NOT_FOUND", message: "Not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ControlPlaneApp router="hash" />);
    expect(await screen.findByRole("heading", { name: "Counsel" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([input]) => !String(input).endsWith("/activity"))).toBe(true);
  });
});
