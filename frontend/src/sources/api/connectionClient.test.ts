import { afterEach, expect, test, vi } from "vitest";

import { ApiClient } from "../../shared/api/client.js";
import { SourceApiClient } from "./connectionClient.js";

afterEach(() => vi.unstubAllGlobals());

function sourceClient(handler: (url: string, init: RequestInit) => Response) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    return handler(call.url, call.init);
  }));
  const api = new ApiClient("http://localhost:8000");
  api.setCsrfToken("csrf-token");
  return { client: new SourceApiClient(api), calls };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("connection start reuses the authenticated CSRF-aware client", async () => {
  const { client, calls } = sourceClient(() => json({
    authorize_url: "https://github.com/apps/ip-risk-agent-v2/installations/new",
    state: "opaque-state",
  }));

  const result = await client.startGithubConnection("vws-1");

  expect(result.state).toBe("opaque-state");
  expect(calls[0]?.url).toBe("http://localhost:8000/api/v1/source-connections/github/install/start");
  expect(new Headers(calls[0]?.init.headers).get("X-CSRF-Token")).toBe("csrf-token");
  expect(calls[0]?.init.credentials).toBe("include");
  expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ risk_workspace_id: "vws-1" });
});

test("GitHub repository selection maps API fields and creates a scoped mount", async () => {
  const { client, calls } = sourceClient((url) => url.endsWith("/repositories")
    ? json({ repositories: [{ id: 7, full_name: "acme/private", owner: "acme", name: "private", private: true, default_branch: "main" }] })
    : json({ server_mount_id: "mount-1", source_workspace_id: "source-1" }));

  const repositories = await client.githubRepositories("pending-12345678");
  const mount = await client.createGithubMount(
    "pending-12345678",
    "vws-1",
    repositories[0]!,
    "release",
  );

  expect(repositories[0]?.fullName).toBe("acme/private");
  expect(mount.serverMountId).toBe("mount-1");
  expect(JSON.parse(String(calls[1]?.init.body))).toMatchObject({
    risk_workspace_id: "vws-1",
    owner: "acme",
    repo: "private",
    tracked_branch: "release",
  });
});

test("server errors remain failures instead of being treated as empty success", async () => {
  const { client } = sourceClient(() => json({ code: "SOURCE_UNAVAILABLE" }, 503));
  await expect(client.startGithubConnection("vws-1")).rejects.toThrow();
});

test("mounting a shared Drive folder needs neither OAuth nor a picker session", async () => {
  const { client, calls } = sourceClient(() => json({
    server_mount_id: "mount-2",
    source_workspace_id: "source-2",
    tracked_file_count: 5,
    truncated: false,
  }));

  const mount = await client.mountSharedDriveFolder(
    "vws-1",
    "https://drive.google.com/drive/folders/folder-1",
  );

  expect(mount.trackedFileCount).toBe(5);
  expect(calls.map((call) => call.url)).toEqual([
    "http://localhost:8000/api/v1/source-connections/google-drive/folders",
  ]);
  expect(calls.some((call) => call.url.includes("picker-session"))).toBe(false);
  expect(calls.some((call) => call.url.includes("google-drive/start"))).toBe(false);
  expect(JSON.parse(String(calls[0]?.init.body))).toMatchObject({
    risk_workspace_id: "vws-1",
    folder_id: "https://drive.google.com/drive/folders/folder-1",
  });
});

test("a mounted folder that turned out to be empty reports zero, not nothing", async () => {
  // 결함 40 — 개수가 없으면 화면에서 빈 폴더와 못 읽는 폴더가 구별되지 않는다.
  const { client } = sourceClient(() => json({
    server_mount_id: "mount-3",
    source_workspace_id: "source-3",
    tracked_file_count: 0,
    truncated: false,
  }));

  const mount = await client.mountSharedDriveFolder("vws-1", "folder-1");

  expect(mount.trackedFileCount).toBe(0);
});

test("the browser is told where to share, and that is all it needs", async () => {
  const { client, calls } = sourceClient(() => json({
    drive_sharing: {
      enabled: true,
      sharing_address: "iprisk-v2-drive@example.iam.gserviceaccount.com",
    },
  }));

  const config = await client.driveSharingRuntimeConfig();

  expect(config.sharingAddress).toBe("iprisk-v2-drive@example.iam.gserviceaccount.com");
  expect(calls[0]?.url).toBe("http://localhost:8000/api/v1/runtime-config");
});

test("desktop revoke is an authenticated CSRF-protected mutation", async () => {
  const { client, calls } = sourceClient(() => new Response(null, { status: 204 }));

  await client.revokeDesktopDevice("device-1");

  expect(calls[0]?.url).toBe("http://localhost:8000/api/v1/desktop/devices/device-1/revoke");
  expect(calls[0]?.init.method).toBe("POST");
  expect(new Headers(calls[0]?.init.headers).get("X-CSRF-Token")).toBe("csrf-token");
});
