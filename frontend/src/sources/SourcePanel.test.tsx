import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ControlPlaneApp } from "../app/control-plane-app.js";
import { SourcePanel } from "./SourcePanel.js";
import type { DrivePickerAdapter } from "./platform/DrivePickerAdapter.js";
import type {
  ConnectLocalMountParams,
  PlatformAdapter,
} from "./platform/PlatformAdapter.js";

const user = { id: "user-1", email: "owner@example.com", display_name: "Owner", avatar_url: null, csrf_token: "csrf-token" };
const workspace = { id: "vws-1", name: "Counsel", description: null, owner_user_id: "user-1", security_policy_version: "security-v1", retention_policy_version: "retention-v1", created_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z", status: "ACTIVE" };
const membership = { id: "member-1", risk_workspace_id: "vws-1", user_id: "user-1", role: "OWNER", status: "ACTIVE", invited_by: "user-1", created_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z" };
const emptySummary = { risk_workspace_id: "vws-1", retention_policy_version: "retention-v1", policy_version: "security-v1", mounts: [], connected_sources: [], recent_access: [], raw_source_persisted: false, analysis_artifact_persisted: false, external_rag_reference_only: true };
const unavailablePicker: DrivePickerAdapter = { available: false, pick: async () => [] };

class FakePlatform implements PlatformAdapter {
  readonly platform = "desktop" as const;
  enrolled = false;
  connectCalls: ConnectLocalMountParams[] = [];

  async chooseLocalDirectory() { return { selectionId: "selection-12345678", displayName: "project" }; }
  async enrollDesktopDevice() { this.enrolled = true; return this.getDesktopConnectionStatus(); }
  async clearDesktopCredential() { this.enrolled = false; return this.getDesktopConnectionStatus(); }
  async connectLocalMount(params: ConnectLocalMountParams) {
    this.connectCalls.push(params);
    return { localMountHandle: "local-1", serverMountId: "mount-1", sourceWorkspaceId: "source-1", status: "ACTIVE" as const };
  }
  async getDesktopConnectionStatus() { return { deviceId: "device-1", mountCount: this.connectCalls.length, enrolled: this.enrolled }; }
  async openLocalOriginal() {}
  async openTrackedArtifact() {}
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function baseResponse(path: string): Response | null {
  if (path.endsWith("/auth/me")) return response(user);
  if (path.endsWith("/workspaces/vws-1/membership")) return response(membership);
  if (path.endsWith("/workspaces/vws-1/security/data-access-summary")) return response(emptySummary);
  if (path.endsWith("/workspaces/vws-1")) return response(workspace);
  return null;
}

describe("SourcePanel product integration", () => {
  it("opens Drive Picker and mounts only the explicitly selected file IDs", async () => {
    window.location.hash = "#/w/vws-1/sources?provider=GOOGLE_DRIVE&connection_id=pending-12345678&status=connected";
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/drive/picker-session")) return response({ access_token: "short-lived-picker-token" });
      if (path.endsWith("/drive/mounts")) return response({ server_mount_id: "mount-7", source_workspace_id: "source-7" });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const picker: DrivePickerAdapter = {
      available: true,
      pick: vi.fn(async () => [{ id: "file-7", name: "Claims", mimeType: "text/plain" }]),
    };
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Select in Google Drive" }));
    expect(await screen.findByText("Claims")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Track selected files" }));

    expect(await screen.findByText("Google Drive files가 연결되었습니다.")).toBeInTheDocument();
    const mount = calls.find((call) => call.path.endsWith("/drive/mounts"));
    expect(JSON.parse(String(mount?.init.body))).toMatchObject({
      risk_workspace_id: "vws-1",
      selected_file_ids: ["file-7"],
    });
  });

  it("completes a GitHub callback with the current workspace and CSRF token", async () => {
    window.location.hash = "#/w/vws-1/sources?provider=GITHUB&connection_id=pending-12345678&status=connected";
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/github/repositories")) return response({ repositories: [{ id: 42, full_name: "acme/private", owner: "acme", name: "private", private: true, default_branch: "main" }] });
      if (path.endsWith("/github/mounts")) return response({ server_mount_id: "mount-42", source_workspace_id: "source-42" });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const platform = new FakePlatform();
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={platform} drivePicker={unavailablePicker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Connect repository" }));

    expect(await screen.findByText("GitHub repository가 연결되었습니다.")).toBeInTheDocument();
    const mount = calls.find((call) => call.path.endsWith("/github/mounts"));
    expect(new Headers(mount?.init.headers).get("X-CSRF-Token")).toBe("csrf-token");
    expect(JSON.parse(String(mount?.init.body))).toMatchObject({
      risk_workspace_id: "vws-1",
      owner: "acme",
      repo: "private",
      tracked_branch: "main",
    });
  });

  it("enrolls Desktop and connects an opaque folder selection without exposing its path", async () => {
    window.location.hash = "#/w/vws-1/sources";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/desktop/enrollment-challenges")) return response({ challenge: "challenge-at-least-32-characters-long", expires_in_seconds: 300 });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const platform = new FakePlatform();
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={platform} drivePicker={unavailablePicker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Local Folder" }));
    await userEvent.click(await screen.findByRole("button", { name: "Enroll this desktop" }));
    await userEvent.click(await screen.findByRole("button", { name: "Choose Folder" }));
    expect(await screen.findByText("project")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect selected folder" }));

    await waitFor(() => expect(platform.connectCalls).toHaveLength(1));
    expect(platform.connectCalls[0]).toEqual({
      selectionId: "selection-12345678",
      riskWorkspaceId: "vws-1",
      includePatterns: [],
      excludePatterns: ["node_modules/**", ".git/**"],
    });
    expect(JSON.stringify(platform.connectCalls[0])).not.toContain("canonicalRootPath");
  });
});
