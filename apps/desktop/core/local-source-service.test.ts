import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import type { DesktopDevice } from "../local-registry/device-identity.js";
import { FileLocalRegistryStore } from "../local-registry/store.js";
import type { ArtifactOpener, DirectoryPicker } from "./local-source-service.js";
import { LocalSourceService } from "./local-source-service.js";

class FakeDirectoryPicker implements DirectoryPicker {
  constructor(private readonly path: string | null) {}
  async pickDirectory(): Promise<string | null> {
    return this.path;
  }
}

class FakeArtifactOpener implements ArtifactOpener {
  openedPaths: string[] = [];
  shownPaths: string[] = [];
  openError = "";

  async openPath(absolutePath: string): Promise<string> {
    this.openedPaths.push(absolutePath);
    return this.openError;
  }

  showInFolder(absolutePath: string): void {
    this.shownPaths.push(absolutePath);
  }
}

function fakeDevice(): DesktopDevice {
  return { deviceId: "dev-1", deviceLabel: "Test-PC", lastSeen: new Date().toISOString() };
}

function setupTempDir(): { dir: string; root: string; registryPath: string } {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-lss-"));
  const root = mkdtempSync(join(tmpdir(), "iprisk-lss-root-"));
  return { dir, root, registryPath: join(dir, "registry.json") };
}

test("chooseTrackedDirectory returns null when user cancels the picker", async () => {
  const { dir, registryPath } = setupTempDir();
  try {
    const service = new LocalSourceService(
      new FakeDirectoryPicker(null),
      new FileLocalRegistryStore(registryPath),
      fakeDevice(),
      new FakeArtifactOpener()
    );

    const result = await service.chooseTrackedDirectory();

    assert.equal(result, null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("chooseTrackedDirectory returns the canonicalized root path", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      new FileLocalRegistryStore(registryPath),
      fakeDevice(),
      new FakeArtifactOpener()
    );

    const result = await service.chooseTrackedDirectory();

    assert.ok(result);
    assert.equal(result?.canonicalRootPath, root);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("connectLocalMount saves a record scoped to this device", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    const registry = new FileLocalRegistryStore(registryPath);
    const service = new LocalSourceService(
      new FakeDirectoryPicker(null),
      registry,
      fakeDevice(),
      new FakeArtifactOpener()
    );

    const record = await service.connectLocalMount({
      canonicalRootPath: root,
      serverMountId: "server-mount-1",
      riskWorkspaceId: "rw1",
      sourceWorkspaceId: "sw1",
      includePatterns: ["**/*.py"],
      excludePatterns: [],
    });

    assert.equal(record.deviceId, "dev-1");
    assert.equal(record.status, "ACTIVE");
    const loaded = await registry.get(record.localMountHandle);
    assert.ok(loaded);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("openTrackedArtifact resolves the path and calls the opener", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    mkdirSync(join(root, "src"), { recursive: true });
    writeFileSync(join(root, "src", "main.py"), "print(1)");

    const registry = new FileLocalRegistryStore(registryPath);
    const opener = new FakeArtifactOpener();
    const service = new LocalSourceService(new FakeDirectoryPicker(null), registry, fakeDevice(), opener);
    const record = await service.connectLocalMount({
      canonicalRootPath: root,
      serverMountId: "server-mount-1",
      riskWorkspaceId: "rw1",
      sourceWorkspaceId: "sw1",
      includePatterns: [],
      excludePatterns: [],
    });

    await service.openTrackedArtifact(record.localMountHandle, "src/main.py");

    assert.equal(opener.openedPaths.length, 1);
    assert.ok(opener.openedPaths[0]?.endsWith(join("src", "main.py")));
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("openTrackedArtifact throws when the opener reports an error", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    mkdirSync(join(root, "src"), { recursive: true });
    writeFileSync(join(root, "src", "main.py"), "print(1)");

    const registry = new FileLocalRegistryStore(registryPath);
    const opener = new FakeArtifactOpener();
    opener.openError = "no application registered for this file type";
    const service = new LocalSourceService(new FakeDirectoryPicker(null), registry, fakeDevice(), opener);
    const record = await service.connectLocalMount({
      canonicalRootPath: root,
      serverMountId: "server-mount-1",
      riskWorkspaceId: "rw1",
      sourceWorkspaceId: "sw1",
      includePatterns: [],
      excludePatterns: [],
    });

    await assert.rejects(() => service.openTrackedArtifact(record.localMountHandle, "src/main.py"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("openTrackedArtifact rejects a path escaping the mount root", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    const registry = new FileLocalRegistryStore(registryPath);
    const service = new LocalSourceService(
      new FakeDirectoryPicker(null),
      registry,
      fakeDevice(),
      new FakeArtifactOpener()
    );
    const record = await service.connectLocalMount({
      canonicalRootPath: root,
      serverMountId: "server-mount-1",
      riskWorkspaceId: "rw1",
      sourceWorkspaceId: "sw1",
      includePatterns: [],
      excludePatterns: [],
    });

    await assert.rejects(() => service.openTrackedArtifact(record.localMountHandle, "../../etc/passwd"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("showTrackedArtifactInFolder calls opener.showInFolder", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    mkdirSync(join(root, "src"), { recursive: true });
    writeFileSync(join(root, "src", "main.py"), "print(1)");

    const registry = new FileLocalRegistryStore(registryPath);
    const opener = new FakeArtifactOpener();
    const service = new LocalSourceService(new FakeDirectoryPicker(null), registry, fakeDevice(), opener);
    const record = await service.connectLocalMount({
      canonicalRootPath: root,
      serverMountId: "server-mount-1",
      riskWorkspaceId: "rw1",
      sourceWorkspaceId: "sw1",
      includePatterns: [],
      excludePatterns: [],
    });

    await service.showTrackedArtifactInFolder(record.localMountHandle, "src/main.py");

    assert.equal(opener.shownPaths.length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("getDesktopConnectionStatus reports device id and mount count", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    const registry = new FileLocalRegistryStore(registryPath);
    const service = new LocalSourceService(
      new FakeDirectoryPicker(null),
      registry,
      fakeDevice(),
      new FakeArtifactOpener()
    );

    const before = await service.getDesktopConnectionStatus();
    assert.equal(before.mountCount, 0);

    await service.connectLocalMount({
      canonicalRootPath: root,
      serverMountId: "server-mount-1",
      riskWorkspaceId: "rw1",
      sourceWorkspaceId: "sw1",
      includePatterns: [],
      excludePatterns: [],
    });

    const after = await service.getDesktopConnectionStatus();
    assert.equal(after.mountCount, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});
