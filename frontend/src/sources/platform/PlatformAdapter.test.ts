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
      return { selectionId: "selection-123", displayName: "example" };
    },
    enrollDesktopDevice: async () => ({ deviceId: "d", mountCount: 0, enrolled: true }),
    clearDesktopCredential: async () => ({ deviceId: "d", mountCount: 0, enrolled: false }),
    connectLocalMount: async () => ({ localMountHandle: "h", serverMountId: "m", sourceWorkspaceId: "s", status: "ACTIVE" as const }),
    openTrackedArtifact: async () => {},
    showTrackedArtifactInFolder: async () => {},
    getDesktopConnectionStatus: async () => ({ deviceId: "d", mountCount: 0, enrolled: true }),
    openLocalOriginal: async () => {},
  };
  const adapter = new ElectronPlatformAdapter(fakeApi);

  const result = await adapter.chooseLocalDirectory();

  expect(called).toBe(true);
  expect(result?.selectionId).toBe("selection-123");
  expect(adapter.platform).toBe("desktop");
});

test("detectPlatformAdapter returns desktop adapter when window.desktopApi is present", () => {
  const fakeApi = {
    chooseTrackedDirectory: async () => null,
    enrollDesktopDevice: async () => ({ deviceId: "d", mountCount: 0, enrolled: true }),
    clearDesktopCredential: async () => ({ deviceId: "d", mountCount: 0, enrolled: false }),
    connectLocalMount: async () => ({ localMountHandle: "h", serverMountId: "m", sourceWorkspaceId: "s", status: "ACTIVE" as const }),
    openTrackedArtifact: async () => {},
    showTrackedArtifactInFolder: async () => {},
    getDesktopConnectionStatus: async () => ({ deviceId: "d", mountCount: 0, enrolled: true }),
    openLocalOriginal: async () => {},
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
