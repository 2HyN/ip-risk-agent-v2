import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { resolveTrackedArtifactPath, TrackedArtifactNotFoundError } from "./artifact-resolver.js";
import { FileLocalRegistryStore, type LocalMountRecord } from "./store.js";

async function setup() {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-resolver-"));
  const root = mkdtempSync(join(tmpdir(), "iprisk-resolver-root-"));
  mkdirSync(join(root, "src"), { recursive: true });
  writeFileSync(join(root, "src", "main.py"), "print(1)");

  const store = new FileLocalRegistryStore(join(dir, "registry.json"));
  const record: LocalMountRecord = {
    localMountHandle: "handle-1",
    serverMountId: "server-1",
    canonicalRootPath: root,
    deviceId: "device-1",
    riskWorkspaceId: "rw1",
    sourceWorkspaceId: "sw1",
    includePatterns: [],
    excludePatterns: [],
    status: "ACTIVE",
  };
  await store.save(record);

  return { dir, root, store };
}

test("resolves the absolute path for a tracked artifact", async () => {
  const { dir, root, store } = await setup();
  try {
    const resolved = await resolveTrackedArtifactPath(store, "handle-1", "src/main.py");
    assert.ok(resolved.endsWith(join("src", "main.py")));
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("throws for unknown mount handle", async () => {
  const { dir, root, store } = await setup();
  try {
    await assert.rejects(
      () => resolveTrackedArtifactPath(store, "never-registered", "src/main.py"),
      TrackedArtifactNotFoundError
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("throws for a path that escapes the registered root", async () => {
  const { dir, root, store } = await setup();
  try {
    await assert.rejects(
      () => resolveTrackedArtifactPath(store, "handle-1", "../../etc/passwd"),
      /escapes root/
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});

test("throws for a tracked artifact that no longer exists on disk", async () => {
  const { dir, root, store } = await setup();
  try {
    await assert.rejects(
      () => resolveTrackedArtifactPath(store, "handle-1", "src/deleted.py"),
      TrackedArtifactNotFoundError
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(root, { recursive: true, force: true });
  }
});
