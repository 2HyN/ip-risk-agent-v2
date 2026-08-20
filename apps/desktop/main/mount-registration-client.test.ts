import test from "node:test";
import assert from "node:assert/strict";

import type { HttpClient } from "./desktop-event-reporter.js";
import { HttpMountRegistrationClient } from "./mount-registration-client.js";

class FakeHttpClient implements HttpClient {
  calls: Array<{ path: string; body: unknown }> = [];
  mountResponse: unknown = { server_mount_id: "server-mount-1", source_workspace_id: "sw-1" };

  async postJson(path: string, body: unknown): Promise<unknown> {
    this.calls.push({ path, body });
    if (path === "/desktop/mounts/register") {
      return this.mountResponse;
    }
    return { status: "ok" };
  }
}

test("registerDevice posts device_id/device_label to /desktop/devices/register", async () => {
  const http = new FakeHttpClient();
  const client = new HttpMountRegistrationClient(http);

  await client.registerDevice("dev-1", "Alice-MacBook");

  assert.equal(http.calls.length, 1);
  assert.equal(http.calls[0]?.path, "/desktop/devices/register");
  assert.deepEqual(http.calls[0]?.body, { device_id: "dev-1", device_label: "Alice-MacBook" });
});

test("registerMount posts snake_case body and returns camelCase result", async () => {
  const http = new FakeHttpClient();
  const client = new HttpMountRegistrationClient(http);

  const result = await client.registerMount({
    riskWorkspaceId: "rw1",
    deviceId: "dev-1",
    includePatterns: ["**/*.py"],
    excludePatterns: [],
  });

  assert.equal(http.calls[0]?.path, "/desktop/mounts/register");
  assert.deepEqual(http.calls[0]?.body, {
    risk_workspace_id: "rw1",
    device_id: "dev-1",
    include_patterns: ["**/*.py"],
    exclude_patterns: [],
  });
  assert.equal(result.serverMountId, "server-mount-1");
  assert.equal(result.sourceWorkspaceId, "sw-1");
});
