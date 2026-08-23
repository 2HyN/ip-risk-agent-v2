import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ControlPlaneApp } from "../app/control-plane-app.js";
import { SourcePanel } from "./SourcePanel.js";
import type {
  ConnectLocalMountParams,
  PlatformAdapter,
} from "./platform/PlatformAdapter.js";

const user = { id: "user-1", email: "owner@example.com", display_name: "Owner", avatar_url: null, csrf_token: "csrf-token" };
const SHARING_ADDRESS = "iprisk-v2-drive@example.iam.gserviceaccount.com";
const sharingConfig = { drive_sharing: { enabled: true, sharing_address: SHARING_ADDRESS } };
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
    tracking_scope_summary: { folder_id: "folder-1" },
    mounted_by_user_id: "user-1",
  }],
};
const connectedGithubSummary = {
  ...emptySummary,
  connected_sources: [{
    mount_id: "mount-github-1",
    alias: "sample_github",
    source_type: "GITHUB",
    provider_account_label: "2HyN",
    status: "ACTIVE",
    tracking_scope_summary: {},
    mounted_by_user_id: "user-1",
  }],
};

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
  it("adds another shared folder to a workspace that already tracks one", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      if (path.endsWith("/security/data-access-summary")) return response(connectedDriveSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/runtime-config")) return response(sharingConfig);
      if (path.endsWith("/google-drive/folders")) {
        return response({
          server_mount_id: "mount-drive-2",
          source_workspace_id: "source-drive-2",
          tracked_file_count: 3,
        });
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    expect(await screen.findByText("1 folder tracked")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add files" }));
    await userEvent.type(
      await screen.findByLabelText("Drive folder link"),
      "https://drive.google.com/drive/folders/folder-2",
    );
    await userEvent.click(screen.getByRole("button", { name: "폴더 붙이기" }));

    expect(await screen.findByText("폴더를 붙였습니다. 파일 3개를 추적합니다.")).toBeInTheDocument();
    const mount = calls.find((call) => call.path.endsWith("/google-drive/folders"));
    expect(JSON.parse(String(mount?.init.body))).toMatchObject({
      risk_workspace_id: "vws-1",
      folder_id: "https://drive.google.com/drive/folders/folder-2",
    });
    // D1 — 밖으로 나갔다 오지 않는다. 승인 화면도 Picker 도 없다.
    expect(calls.some((call) => call.path.includes("google-drive/start"))).toBe(false);
    expect(calls.some((call) => call.path.includes("picker-session"))).toBe(false);
    expect(calls.filter((call) => call.path.endsWith("/security/data-access-summary"))).toHaveLength(2);
  });

  it("renders provider-neutral artifact, analysis, and risk state with detail navigation", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const summary = {
      ...connectedDriveSummary,
      tracked_artifacts: [
        {
          artifact_id: "artifact-drive-1",
          change_event_id: "change-artifact-drive-1",
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
          change_event_id: "change-artifact-local-1",
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

    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

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

  it("says the folder is already tracked instead of mounting it twice", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      calls.push(path);
      if (path.endsWith("/security/data-access-summary")) return response(connectedDriveSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/runtime-config")) return response(sharingConfig);
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Add files" }));
    await userEvent.type(await screen.findByLabelText("Drive folder link"), "folder-1");
    await userEvent.click(screen.getByRole("button", { name: "폴더 붙이기" }));

    expect(await screen.findByRole("status")).toHaveTextContent("이미 추적하고 있습니다");
    expect(calls.some((path) => path.endsWith("/google-drive/folders"))).toBe(false);
  });

  it("mounts a shared folder and says how many files it found", async () => {
    window.location.hash = "#/w/vws-1/sources";
    const calls: Array<{ path: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init: init ?? {} });
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/runtime-config")) return response(sharingConfig);
      if (path.endsWith("/google-drive/folders")) {
        return response({
          server_mount_id: "mount-7",
          source_workspace_id: "source-7",
          tracked_file_count: 5,
        });
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Google Drive" }));
    expect(await screen.findByText(SHARING_ADDRESS)).toBeInTheDocument();
    await userEvent.type(await screen.findByLabelText("Drive folder link"), "folder-7");
    await userEvent.click(screen.getByRole("button", { name: "폴더 붙이기" }));

    expect(await screen.findByText("폴더를 붙였습니다. 파일 5개를 추적합니다.")).toBeInTheDocument();
    expect(calls.filter((call) => call.path.endsWith("/security/data-access-summary"))).toHaveLength(2);
  });

  it("says zero out loud so an empty folder is not mistaken for a broken one", async () => {
    // 결함 40 — 사용자가 이 둘을 구별하지 못해 폴더 대신 파일을 골랐다.
    window.location.hash = "#/w/vws-1/sources";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/runtime-config")) return response(sharingConfig);
      if (path.endsWith("/google-drive/folders")) {
        return response({
          server_mount_id: "mount-8",
          source_workspace_id: "source-8",
          tracked_file_count: 0,
        });
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Google Drive" }));
    await userEvent.type(await screen.findByLabelText("Drive folder link"), "folder-8");
    await userEvent.click(screen.getByRole("button", { name: "폴더 붙이기" }));

    expect(
      await screen.findByText("폴더를 붙였습니다. 안에 파일이 없어 아직 추적할 것이 없습니다."),
    ).toBeInTheDocument();
  });

  it("tells the user to share the folder, with the address, when Drive refuses it", async () => {
    window.location.hash = "#/w/vws-1/sources";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/runtime-config")) return response(sharingConfig);
      if (path.endsWith("/google-drive/folders")) {
        return response({
          detail: {
            code: "DRIVE_FOLDER_NOT_SHARED",
            sharing_address: SHARING_ADDRESS,
            message: "이 폴더가 아직 공유되지 않았습니다. " + SHARING_ADDRESS + " 를 뷰어로 공유해 주세요.",
          },
        }, 409);
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Google Drive" }));
    await userEvent.type(await screen.findByLabelText("Drive folder link"), "folder-9");
    await userEvent.click(screen.getByRole("button", { name: "폴더 붙이기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("아직 공유되지 않았습니다");
    expect(screen.getByRole("alert")).toHaveTextContent(SHARING_ADDRESS);
  });

  it("refuses a file chosen as a folder and says so", async () => {
    // 결함 37 — 예전에는 아무것도 추적하지 않는 마운트가 성공으로 보였다.
    window.location.hash = "#/w/vws-1/sources";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/runtime-config")) return response(sharingConfig);
      if (path.endsWith("/google-drive/folders")) {
        return response({
          detail: {
            code: "DRIVE_NOT_A_FOLDER",
            message: "폴더가 아니라 파일입니다. 추적할 파일들을 담은 폴더를 공유해 주세요.",
          },
        }, 400);
      }
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "Google Drive" }));
    await userEvent.type(await screen.findByLabelText("Drive folder link"), "doc-1");
    await userEvent.click(screen.getByRole("button", { name: "폴더 붙이기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("폴더가 아니라 파일입니다");
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
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={platform} /> }} />);

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

  it("lists repositories from a live GitHub connection instead of leaving for GitHub", async () => {
    // 저장소를 더 붙이려는 사람이 먼저 누르는 것은 "Add Source" 다. 거기서 설치
    // 화면으로 보내면 GitHub 은 저장소 선택이 바뀔 때만 돌려보내므로, 새로 고를
    // 것이 없는 사람은 돌아오지 못한다.
    window.location.hash = "#/w/vws-1/sources";
    let installStarted = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/workspaces/vws-1/security/data-access-summary")) return response(connectedGithubSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/github/install/start")) { installStarted = true; return response({ authorize_url: "https://github.invalid/x", state: "s" }); }
      if (path.endsWith("/github/repositories")) return response({ repositories: [{ id: 7, full_name: "2HyN/sample_github_deps", owner: "2HyN", name: "sample_github_deps", private: false, default_branch: "main" }] });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "GitHub Repository" }));

    expect(await screen.findByText("Add another repository")).toBeInTheDocument();
    expect(installStarted).toBe(false);
  });

  it("still offers a way to GitHub for a repository the installation cannot reach", async () => {
    // 설치에 없는 저장소는 GitHub 에서만 넣을 수 있다 — App 이 스스로 접근 권한을
    // 얻는 API 는 없다. 기존 연결을 쓰게 하면서 이 길까지 없애 버린 적이 있다.
    window.location.hash = "#/w/vws-1/sources";
    const visited: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/workspaces/vws-1/security/data-access-summary")) return response(connectedGithubSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      if (path.endsWith("/github/install/start")) { visited.push(path); return response({ authorize_url: "https://github.invalid/install", state: "s" }); }
      if (path.endsWith("/github/repositories")) return response({ repositories: [] });
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    await userEvent.click(await screen.findByRole("button", { name: "GitHub 에서 저장소 추가" }));

    await waitFor(() => expect(visited).toHaveLength(1));
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
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={platform} /> }} />);

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

  it("requests a re-analysis without needing a file change", async () => {
    // 재현을 파일 재업로드에 의존하면 디버깅도 검증도 느려진다. 변경 없이 같은
    // artifact 를 다시 돌릴 수 있어야 한다.
    window.location.hash = "#/w/vws-1/sources";
    const reanalyzed: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/security/reanalyze")) {
        reanalyzed.push(JSON.parse(String(init?.body)));
        return response({ status: "queued" });
      }
      if (path.endsWith("/security/data-access-summary")) {
        return response({
          ...connectedDriveSummary,
          tracked_artifacts: [
            {
              artifact_id: "artifact-drive-1",
              change_event_id: "change-artifact-drive-1",
              mount_id: "mount-drive-1",
              source_type: "GOOGLE_DRIVE",
              source_context: "Google Drive a1b2c3d4",
              display_name: "Claims.txt",
              logical_path: "Claims.txt",
              availability: "AVAILABLE",
              latest_revision: "rev-2",
              change_status: "DONE",
              analysis_status: "SUCCEEDED",
              risk_count: 0,
              active_risk_count: 0,
              first_risk_id: null,
              highest_risk_priority: null,
              updated_at: "2026-08-21T00:00:00Z",
            },
          ],
        });
      }
      const base = baseResponse(path);
      if (base !== null) return base;
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    const [button] = await screen.findAllByRole("button", { name: "다시 검사" });
    expect(button).toBeDefined();
    await userEvent.click(button as HTMLElement);

    await waitFor(() => expect(reanalyzed).toHaveLength(1));
    expect(reanalyzed[0]).toEqual({ change_event_id: "change-artifact-drive-1" });
  });

  it("tells the user the only way to stop tracking a file", async () => {
    // 폴더를 보는 지금 "이 파일만 추적 해제" 는 성립하지 않는다 (§6.1 · 1-F).
    // 범위에서 뺄 방법이 없고, Risk 만 닫아 두면 그 파일의 다음 변경에 되살아난다.
    window.location.hash = "#/w/vws-1/sources";
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      calls.push(path);
      if (path.endsWith("/security/data-access-summary")) return response(connectedDriveSummary);
      const base = baseResponse(path);
      if (base !== null) return base;
      return response({ code: "NOT_FOUND" }, 404);
    }));
    render(<ControlPlaneApp router="hash" integration={{ sourcePanel: <SourcePanel platform={new FakePlatform()} /> }} />);

    expect(await screen.findByText("1 folder tracked")).toBeInTheDocument();

    // 추적을 끊는 요청을 서버로 보내지 않는다. 보낼 곳이 없어졌다.
    expect(calls.some((path) => path.endsWith("/drive/untrack"))).toBe(false);
  });
});
