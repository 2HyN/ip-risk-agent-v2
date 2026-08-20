import { expect, test } from "vitest";

import {
  detectPlatformAdapter,
  ElectronPlatformAdapter,
  WebPlatformAdapter,
} from "./PlatformAdapter.js";

test("detectPlatformAdapter returns web adapter when window is unavailable (Node/SSR context)", () => {
  const adapter = detectPlatformAdapter();
  expect(adapter.platform).toBe("web");
});

test("WebPlatformAdapter.chooseLocalDirectory always returns null", async () => {
  const adapter = new WebPlatformAdapter();
  const result = await adapter.chooseLocalDirectory();
  expect(result).toBeNull();
});

test("WebPlatformAdapter.openTrackedArtifact throws", async () => {
  const adapter = new WebPlatformAdapter();
  await expect(adapter.openTrackedArtifact("h", "p")).rejects.toThrow();
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

  expect(called).toBe(true);
  expect(result?.canonicalRootPath).toBe("/tmp/example");
  expect(adapter.platform).toBe("desktop");
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
    expect(adapter.platform).toBe("desktop");
  } finally {
    delete (globalThis as { window?: unknown }).window;
  }
});
