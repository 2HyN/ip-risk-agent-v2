import { afterEach, expect, test, vi } from "vitest";

import { ApiClient } from "../shared/api/client.js";
import { SourceApiClient } from "./api/connectionClient.js";
import { createOpenOriginalHandler } from "./openOriginal.js";
import type { PlatformAdapter } from "./platform/PlatformAdapter.js";

afterEach(() => vi.unstubAllGlobals());

function platform() {
  const opened: Array<[string, string]> = [];
  const value: PlatformAdapter = {
    platform: "desktop",
    chooseLocalDirectory: async () => null,
    enrollDesktopDevice: async () => ({ deviceId: "device-1", mountCount: 0, enrolled: true }),
    clearDesktopCredential: async () => ({ deviceId: "device-1", mountCount: 0, enrolled: false }),
    connectLocalMount: async () => ({ localMountHandle: "h", serverMountId: "m", sourceWorkspaceId: "s", status: "ACTIVE" }),
    getDesktopConnectionStatus: async () => ({ deviceId: "device-1", mountCount: 0, enrolled: true }),
    openLocalOriginal: async (deviceId, artifactId) => { opened.push([deviceId, artifactId]); },
    openTrackedArtifact: async () => {},
  };
  return { value, opened };
}

function sourceApi(body: unknown): SourceApiClient {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })));
  const client = new ApiClient();
  client.setCsrfToken("csrf");
  return new SourceApiClient(client);
}

test("Open Original rejects a provider lookalike host in the browser boundary", async () => {
  const { value } = platform();
  const open = vi.fn();
  const handler = createOpenOriginalHandler(sourceApi({
    original_source_type: "PROVIDER_URL",
    provider_url: "https://github.com.evil.example/acme/repo",
    device_id: null,
    source_artifact_id: null,
    metadata_safe: {},
  }), value, open);

  await expect(handler({ workspaceId: "vws-1", artifactId: "artifact-1", action: "SOURCE_OPEN_ORIGINAL", sourceType: "GITHUB" })).rejects.toThrow("untrusted");
  expect(open).not.toHaveBeenCalled();
});

test("Local Open Original sends only opaque IDs to the Desktop main process", async () => {
  const { value, opened } = platform();
  const handler = createOpenOriginalHandler(sourceApi({
    original_source_type: "LOCAL_DEVICE",
    provider_url: null,
    device_id: "device-1",
    source_artifact_id: "opaque-artifact-id",
    metadata_safe: {},
  }), value);

  await handler({ workspaceId: "vws-1", artifactId: "artifact-1", action: "SOURCE_OPEN_ORIGINAL", sourceType: "LOCAL" });
  expect(opened).toEqual([["device-1", "opaque-artifact-id"]]);
});
