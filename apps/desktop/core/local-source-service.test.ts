import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import type { DesktopDevice } from "../local-registry/device-identity.js";
import { FileLocalRegistryStore } from "../local-registry/store.js";
import type {
  MountRegistrationClient,
  RegisterMountParams,
  RegisterMountResult,
} from "../main/mount-registration-client.js";
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

class FakeMountRegistrationClient implements MountRegistrationClient {
  registeredDevices: Array<{ deviceId: string; deviceLabel: string }> = [];
  registerMountCalls: RegisterMountParams[] = [];
  nextResult: RegisterMountResult = { serverMountId: "server-mount-1", sourceWorkspaceId: "sw1" };

  async registerDevice(deviceId: string, deviceLabel: string): Promise<void> {
    this.registeredDevices.push({ deviceId, deviceLabel });
  }

  async registerMount(params: RegisterMountParams): Promise<RegisterMountResult> {
    this.registerMountCalls.push(params);
    return this.nextResult;
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

async function selectDirectory(service: LocalSourceService): Promise<string> {
  const selection = await service.chooseTrackedDirectory();
  assert.ok(selection);
  return selection.selectionId;
}

test("chooseTrackedDirectory returns null when user cancels the picker", async () => {
  const { dir, registryPath } = setupTempDir();
  try {
    const service = new LocalSourceService(
      new FakeDirectoryPicker(null),
      new FileLocalRegistryStore(registryPath),
      fakeDevice(),
      new FakeArtifactOpener(),
      new FakeMountRegistrationClient()
    );

    const result = await service.chooseTrackedDirectory();

    assert.equal(result, null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("chooseTrackedDirectory returns an opaque selection without the absolute path", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      new FileLocalRegistryStore(registryPath),
      fakeDevice(),
      new FakeArtifactOpener(),
      new FakeMountRegistrationClient()
    );

    const result = await service.chooseTrackedDirectory();

    assert.ok(result);
    assert.equal(result?.displayName, root.split(/[\\/]/u).at(-1));
    assert.equal("canonicalRootPath" in result, false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("connectLocalMount registers with the server first, then saves locally with the returned IDs", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    const registry = new FileLocalRegistryStore(registryPath);
    const registrationClient = new FakeMountRegistrationClient();
    registrationClient.nextResult = { serverMountId: "server-mount-42", sourceWorkspaceId: "sw-42" };
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      registry,
      fakeDevice(),
      new FakeArtifactOpener(),
      registrationClient
    );

    const selectionId = await selectDirectory(service);
    const record = await service.connectLocalMount({
      selectionId,
      riskWorkspaceId: "rw1",
      includePatterns: ["**/*.py"],
      excludePatterns: [],
    });

    assert.equal(registrationClient.registerMountCalls.length, 1);
    assert.equal(registrationClient.registerMountCalls[0]?.riskWorkspaceId, "rw1");
    assert.equal(registrationClient.registerMountCalls[0]?.deviceId, "dev-1");
    assert.deepEqual(registrationClient.registerMountCalls[0]?.includePatterns, ["**/*.py"]);

    assert.equal(record.serverMountId, "server-mount-42");
    assert.equal(record.sourceWorkspaceId, "sw-42");
    assert.equal(record.deviceId, "dev-1");
    assert.equal(record.status, "ACTIVE");

    const loaded = await registry.get(record.localMountHandle);
    assert.ok(loaded);
    assert.equal(loaded?.serverMountId, "server-mount-42");
    await assert.rejects(
      () => service.connectLocalMount({
        selectionId,
        riskWorkspaceId: "rw1",
        includePatterns: [],
        excludePatterns: [],
      }),
      /unknown or consumed/,
    );
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
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      registry,
      fakeDevice(),
      opener,
      new FakeMountRegistrationClient()
    );
    const record = await service.connectLocalMount({
      selectionId: await selectDirectory(service),
      riskWorkspaceId: "rw1",
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
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      registry,
      fakeDevice(),
      opener,
      new FakeMountRegistrationClient()
    );
    const record = await service.connectLocalMount({
      selectionId: await selectDirectory(service),
      riskWorkspaceId: "rw1",
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
      new FakeDirectoryPicker(root),
      registry,
      fakeDevice(),
      new FakeArtifactOpener(),
      new FakeMountRegistrationClient()
    );
    const record = await service.connectLocalMount({
      selectionId: await selectDirectory(service),
      riskWorkspaceId: "rw1",
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
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      registry,
      fakeDevice(),
      opener,
      new FakeMountRegistrationClient()
    );
    const record = await service.connectLocalMount({
      selectionId: await selectDirectory(service),
      riskWorkspaceId: "rw1",
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

test("openLocalOriginal resolves an opaque artifact only on the owning device and mount", async () => {
  const { dir, root, registryPath } = setupTempDir();
  try {
    mkdirSync(join(root, "src"), { recursive: true });
    writeFileSync(join(root, "src", "main.py"), "print(1)");
    const opener = new FakeArtifactOpener();
    const service = new LocalSourceService(
      new FakeDirectoryPicker(root),
      new FileLocalRegistryStore(registryPath),
      fakeDevice(),
      opener,
      new FakeMountRegistrationClient(),
    );
    await service.connectLocalMount({
      selectionId: await selectDirectory(service),
      riskWorkspaceId: "rw1",
      includePatterns: [],
      excludePatterns: [],
    });
    const artifactId = Buffer.from(
      ["dev-1", "server-mount-1", "src/main.py"].join("\u001f"),
    ).toString("base64url");

    await service.openLocalOriginal("dev-1", artifactId);

    assert.equal(opener.openedPaths.length, 1);
    await assert.rejects(() => service.openLocalOriginal("other-device", artifactId));
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
      new FakeDirectoryPicker(root),
      registry,
      fakeDevice(),
      new FakeArtifactOpener(),
      new FakeMountRegistrationClient()
    );

    const before = await service.getDesktopConnectionStatus();
    assert.equal(before.mountCount, 0);
    assert.equal(before.deviceId, "dev-1");

    await service.connectLocalMount({
      selectionId: await selectDirectory(service),
      riskWorkspaceId: "rw1",
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
