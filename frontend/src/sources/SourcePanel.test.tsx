import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ControlPlaneApp } from "../app/control-plane-app.js";
import { SourcePanel } from "./SourcePanel.js";
import {
  GoogleDrivePickerAdapter,
  type DrivePickerAdapter,
  type DrivePickerFile,
} from "./platform/DrivePickerAdapter.js";
import type {
  ConnectLocalMountParams,
  PlatformAdapter,
} from "./platform/PlatformAdapter.js";

const user = { id: "user-1", email: "owner@example.com", display_name: "Owner", avatar_url: null, csrf_token: "csrf-token" };
const workspace = { id: "vws-1", name: "Counsel", description: null, owner_user_id: "user-1", security_policy_version: "security-v1", retention_policy_version: "retention-v1", created_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z", status: "ACTIVE" };
const membership = { id: "member-1", risk_workspace_id: "vws-1", user_id: "user-1", role: "OWNER", status: "ACTIVE", invited_by: "user-1", created_at: "2026-08-17T00:00:00Z", updated_at: "2026-08-17T00:00:00Z" };
const emptySummary = { risk_workspace_id: "vws-1", retention_policy_version: "retention-v1", policy_version: "security-v1", mounts: [], connected_sources: [], recent_access: [], raw_source_persisted: false, analysis_artifact_persisted: false, external_rag_reference_only: true };
const connectedDriveSummary = {
  ...emptySummary,
  connected_sources: [{
    mount_id: "mount-drive-1",
    alias: "Google Drive a1b2c3d4",
    source_type: "GOOGLE_DRIVE",
    provider_account_label: "owner@example.com",
    status: "ACTIVE",
    tracking_scope_summary: { selected_file_ids: ["file-1"] },
    mounted_by_user_id: "user-1",
  }],
};
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
  delete window.google;
  delete window.gapi;
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

function googlePicker(selected: DrivePickerFile[]): GoogleDrivePickerAdapter {
  const response = { ACTION: "action", DOCUMENTS: "docs" };
  const document = { ID: "id", MIME_TYPE: "mimeType", NAME: "name" };
  const action = { CANCEL: "cancel", ERROR: "error", PICKED: "picked" };
  class DocsView {
    setIncludeFolders() { return this; }
    setSelectFolderEnabled() { return this; }
  }
  class PickerBuilder {
    private callback: ((data: unknown) => void) | null = null;
    addView() { return this; }
    enableFeature() { return this; }
    setOAuthToken() { return this; }
    setDeveloperKey() { return this; }
    setAppId() { return this; }
    setOrigin() { return this; }
    setCallback(value: (data: unknown) => void) {
      this.callback = value;
      return this;
    }
    build() {
      const callbackData = {
        [response.ACTION]: action.PICKED,
        [response.DOCUMENTS]: selected.map((file) => ({
          [document.ID]: file.id,
          [document.NAME]: file.name,
          [document.MIME_TYPE]: file.mimeType,
        })),
      };
      return {
        setVisible: () => queueMicrotask(() => this.callback?.(callbackData)),
      };
    }
  }
  window.google = { picker: {
    Action: action,
    Response: response,
    Document: document,
    Feature: { MULTISELECT_ENABLED: "multiselectEnabled" },
    ViewId: { DOCS: "all" },
    DocsView,
    PickerBuilder,
  } };
  return new GoogleDrivePickerAdapter(async () => ({
    enabled: true,
    browserApiKey: "restricted-browser-key",
    cloudProjectNumber: "123456789012",
  }));
}

describe("SourcePanel product integration", () => {
  it("adds multiple files through the ACTIVE mount without restarting OAuth", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      if (path.endsWith("/security/data-access-summary")) return response(connectedDriveSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/source-mounts/mount-drive-1/drive/picker-session")) {
        return response({ access_token: "active-picker-token" });
      }
      if (path.endsWith("/source-mounts/mount-drive-1/drive/mounts")) {
        return response({ server_mount_id: "mount-drive-2", source_workspace_id: "source-drive-2" });
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const picker: DrivePickerAdapter = {
      available: true,
      pick: vi.fn(async () => [
        { id: "file-1", name: "Already tracked", mimeType: "text/plain" },
        { id: "file-2", name: "Claims", mimeType: "text/plain" },
        { id: "file-3", name: "Prior art", mimeType: "application/pdf" },
      ]),
    };
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    expect(await screen.findByText("1 file tracked")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add files" }));
    expect(screen.getByRole("heading", { name: "Add Source" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Select in Google Drive" }));

    expect(await screen.findByText("Additional Google Drive files are now tracked.")).toBeInTheDocument();
    const mount = calls.find((call) => call.path.endsWith("/source-mounts/mount-drive-1/drive/mounts"));
    expect(JSON.parse(String(mount?.init.body))).toMatchObject({
      risk_workspace_id: "vws-1",
      selected_file_ids: ["file-2", "file-3"],
    });
    expect(calls.some((call) => call.path.includes("google-drive/start"))).toBe(false);
    expect(calls.filter((call) => call.path.endsWith("/security/data-access-summary"))).toHaveLength(2);
  });

  it("renders provider-neutral artifact, analysis, and risk state with detail navigation", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const summary = {
      ...connectedDriveSummary,
      tracked_artifacts: [
        {
          artifact_id: "artifact-drive-1",
          mount_id: "mount-drive-1",
          source_type: "GOOGLE_DRIVE",
          source_context: "Google Drive a1b2c3d4",
          display_name: "Claims.txt",
          logical_path: "Claims.txt",
          availability: "AVAILABLE",
          latest_revision: "rev-2",
          change_status: "DONE",
          analysis_status: "SUCCEEDED",
          risk_count: 2,
          active_risk_count: 1,
          first_risk_id: "risk-7",
          highest_risk_priority: "HIGH",
          updated_at: "2026-08-21T00:00:00Z",
        },
        {
          artifact_id: "artifact-local-1",
          mount_id: "mount-local-1",
          source_type: "LOCAL",
          source_context: "Desktop project",
          display_name: "package.json",
          logical_path: "web/package.json",
          availability: "AVAILABLE",
          latest_revision: "sha-1",
          change_status: "PROCESSING",
          analysis_status: "RUNNING",
          risk_count: 0,
          active_risk_count: 0,
          first_risk_id: null,
          highest_risk_priority: null,
          updated_at: "2026-08-20T00:00:00Z",
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/security/data-access-summary")) return response(summary);
      const base = baseResponse(path);
      if (base !== null) return base;
      return response({ code: "NOT_FOUND" }, 404);
    }));

    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={unavailablePicker} /> }} />);

    expect(await screen.findByRole("heading", { name: "Tracked artifacts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Claims.txt" })).toBeInTheDocument();
    expect(screen.getByText("Change: DONE · Analysis: SUCCEEDED")).toBeInTheDocument();
    expect(screen.getByText("1 active · 2 total risks")).toBeInTheDocument();
    expect(screen.getByText("package.json")).toBeInTheDocument();
    expect(screen.getByText("No risk has been produced for the latest analyzed state.")).toBeInTheDocument();
    const artifactLinks = screen.getAllByRole("link", { name: "View artifact analysis" });
    expect(artifactLinks[0]!).toHaveAttribute("href", "#/w/vws-1/sources/artifacts/artifact-drive-1");
    expect(screen.getByRole("heading", { name: "Add Source" })).toBeInTheDocument();

    await userEvent.click(artifactLinks[0]!);
    expect(await screen.findByText("Latest revision")).toBeInTheDocument();
    expect(screen.getByText("rev-2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open risk findings and evidence" }))
      .toHaveAttribute("href", "#/w/vws-1/risks/risk-7");
  });

  it("treats selecting only an already tracked Drive file as a no-op", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      calls.push(path);
      if (path.endsWith("/security/data-access-summary")) return response(connectedDriveSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/picker-session")) return response({ access_token: "active-picker-token" });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const picker: DrivePickerAdapter = {
      available: true,
      pick: vi.fn(async () => [{ id: "file-1", name: "Already tracked", mimeType: "text/plain" }]),
    };
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Add files" }));
    await userEvent.click(screen.getByRole("button", { name: "Select in Google Drive" }));

    expect(await screen.findByText("All selected files are already tracked in this workspace.")).toBeInTheDocument();
    expect(calls.some((path) => path.endsWith("/drive/mounts"))).toBe(false);
  });

  it("keeps an ACTIVE connection available for retry after an additional mount failure", async () => {
    window.location.hash = "#/w/vws-1/sources";
    let failMount = true;
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      calls.push(path);
      if (path.endsWith("/security/data-access-summary")) return response(connectedDriveSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/picker-session")) return response({ access_token: "active-picker-token" });
      if (path.endsWith("/drive/mounts")) {
        if (failMount) return response({ code: "SOURCE_UNAVAILABLE" }, 503);
        return response({ server_mount_id: "mount-drive-2", source_workspace_id: "source-drive-2" });
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const picker: DrivePickerAdapter = {
      available: true,
      pick: vi.fn(async () => [{ id: "file-2", name: "Claims", mimeType: "text/plain" }]),
    };
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Add files" }));
    await userEvent.click(screen.getByRole("button", { name: "Select in Google Drive" }));
    expect(await screen.findByRole("button", { name: "Retry tracking selected files" })).toBeInTheDocument();
    expect(screen.getByText("Claims")).toBeInTheDocument();

    failMount = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry tracking selected files" }));
    expect(await screen.findByText("Additional Google Drive files are now tracked.")).toBeInTheDocument();
    expect(calls.filter((path) => path.endsWith("/drive/mounts"))).toHaveLength(2);
  });

  it("mounts Picker-selected Drive files immediately and refreshes source state", async () => {
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
    const picker = googlePicker([
      { id: "file-7", name: "Claims", mimeType: "text/plain" },
      { id: "file-8", name: "Prior art", mimeType: "application/pdf" },
    ]);
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Select in Google Drive" }));

    expect(await screen.findByText("Google Drive files가 연결되었습니다.")).toBeInTheDocument();
    const mount = calls.find((call) => call.path.endsWith("/drive/mounts"));
    expect(mount?.path).toContain("/source-connections/pending-12345678/");
    expect(JSON.parse(String(mount?.init.body))).toMatchObject({
      risk_workspace_id: "vws-1",
      selected_file_ids: ["file-7", "file-8"],
    });
    expect(calls.filter((call) => call.path.endsWith("/security/data-access-summary")))
      .toHaveLength(2);
  });

  it("keeps the selection and shows a retry action when Drive mount creation fails", async () => {
    window.location.hash = "#/w/vws-1/sources?provider=GOOGLE_DRIVE&connection_id=pending-12345678&status=connected";
    let failMount = true;
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/drive/picker-session")) return response({ access_token: "short-lived-picker-token" });
      if (path.endsWith("/drive/mounts")) {
        if (failMount) return response({ code: "SOURCE_UNAVAILABLE" }, 503);
        return response({ server_mount_id: "mount-7", source_workspace_id: "source-7" });
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const picker: DrivePickerAdapter = {
      available: true,
      pick: vi.fn(async () => [{ id: "file-7", name: "Claims", mimeType: "text/plain" }]),
    };
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Select in Google Drive" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("mount로 만들지 못했습니다");
    expect(screen.getByText("Claims")).toBeInTheDocument();
    expect(calls.filter((call) => call.path.endsWith("/drive/mounts"))).toHaveLength(1);

    failMount = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry tracking selected files" }));
    expect(await screen.findByText("Google Drive files가 연결되었습니다.")).toBeInTheDocument();
    expect(calls.filter((call) => call.path.endsWith("/drive/mounts"))).toHaveLength(2);
  });

  it("shows a safe error and never calls mounts when Picker callback parsing fails", async () => {
    window.location.hash = "#/w/vws-1/sources?provider=GOOGLE_DRIVE&connection_id=pending-12345678&status=connected";
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/drive/picker-session")) return response({ access_token: "short-lived-picker-token" });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    const picker: DrivePickerAdapter = {
      available: true,
      pick: vi.fn(async () => { throw new Error("invalid_documents"); }),
    };
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} drivePicker={picker} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Select in Google Drive" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("선택 결과를 확인하지 못했습니다");
    expect(calls.some((call) => call.path.endsWith("/drive/mounts"))).toBe(false);
    expect(screen.queryByText("invalid_documents")).not.toBeInTheDocument();
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
