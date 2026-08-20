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
    authorize_url: "https://accounts.google.com/o/oauth2/v2/auth",
    state: "opaque-state",
  }));

  const result = await client.startDriveConnection("vws-1");

  expect(result.state).toBe("opaque-state");
  expect(calls[0]?.url).toBe("http://localhost:8000/api/v1/source-connections/google-drive/start");
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

test("desktop revoke is an authenticated CSRF-protected mutation", async () => {
  const { client, calls } = sourceClient(() => new Response(null, { status: 204 }));

  await client.revokeDesktopDevice("device-1");

  expect(calls[0]?.url).toBe("http://localhost:8000/api/v1/desktop/devices/device-1/revoke");
  expect(calls[0]?.init.method).toBe("POST");
  expect(new Headers(calls[0]?.init.headers).get("X-CSRF-Token")).toBe("csrf-token");
});
