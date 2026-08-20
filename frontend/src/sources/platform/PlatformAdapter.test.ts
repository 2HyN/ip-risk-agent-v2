import test from "node:test";
import assert from "node:assert/strict";

import {
  detectPlatformAdapter,
  ElectronPlatformAdapter,
  WebPlatformAdapter,
} from "./PlatformAdapter.js";

test("detectPlatformAdapter returns web adapter when window is unavailable (Node/SSR context)", () => {
  const adapter = detectPlatformAdapter();
  assert.equal(adapter.platform, "web");
});

test("WebPlatformAdapter.chooseLocalDirectory always returns null", async () => {
  const adapter = new WebPlatformAdapter();
  const result = await adapter.chooseLocalDirectory();
  assert.equal(result, null);
});

test("WebPlatformAdapter.openTrackedArtifact throws", async () => {
  const adapter = new WebPlatformAdapter();
  await assert.rejects(() => adapter.openTrackedArtifact("h", "p"));
});

test("ElectronPlatformAdapter.chooseLocalDirectory delegates to desktopApi", async () => {
  let called = false;
  const fakeApi = {
    chooseTrackedDirectory: async () => {
      called = true;
      return { canonicalRootPath: "/tmp/example" };
    },
    connectLocalMount: async () => ({}),
    openTrackedArtifact: async () => {},
    showTrackedArtifactInFolder: async () => {},
    getDesktopConnectionStatus: async () => ({ deviceId: "d", mountCount: 0 }),
  };
  const adapter = new ElectronPlatformAdapter(fakeApi);

  const result = await adapter.chooseLocalDirectory();

  assert.equal(called, true);
  assert.equal(result?.canonicalRootPath, "/tmp/example");
  assert.equal(adapter.platform, "desktop");
});

test("detectPlatformAdapter returns desktop adapter when window.desktopApi is present", () => {
  const fakeApi = {
    chooseTrackedDirectory: async () => null,
    connectLocalMount: async () => ({}),
    openTrackedArtifact: async () => {},
    showTrackedArtifactInFolder: async () => {},
    getDesktopConnectionStatus: async () => ({ deviceId: "d", mountCount: 0 }),
  };
  (globalThis as unknown as { window: { desktopApi: typeof fakeApi } }).window = {
    desktopApi: fakeApi,
  };

  try {
    const adapter = detectPlatformAdapter();
    assert.equal(adapter.platform, "desktop");
  } finally {
    delete (globalThis as { window?: unknown }).window;
  }
});
