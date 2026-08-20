import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  FileLocalRegistryStore,
  toServerMountContext,
  type LocalMountRecord,
} from "./store.js";

function makeRecord(overrides: Partial<LocalMountRecord> = {}): LocalMountRecord {
  return {
    localMountHandle: "handle-1",
    serverMountId: "server-mount-1",
    canonicalRootPath: "/Users/someone/very/secret/project",
    deviceId: "device-1",
    riskWorkspaceId: "rw1",
    sourceWorkspaceId: "sw1",
    includePatterns: ["**/*.py"],
    excludePatterns: ["**/node_modules/**"],
    status: "ACTIVE",
    ...overrides,
  };
}

test("save then get roundtrip", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-registry-"));
  const store = new FileLocalRegistryStore(join(dir, "registry.json"));
  try {
    await store.save(makeRecord());
    const loaded = await store.get("handle-1");
    assert.ok(loaded);
    assert.equal(loaded?.serverMountId, "server-mount-1");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("get missing handle returns null", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-registry-"));
  const store = new FileLocalRegistryStore(join(dir, "registry.json"));
  try {
    const loaded = await store.get("never-saved");
    assert.equal(loaded, null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("list returns all saved records", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-registry-"));
  const store = new FileLocalRegistryStore(join(dir, "registry.json"));
  try {
    await store.save(makeRecord({ localMountHandle: "a" }));
    await store.save(makeRecord({ localMountHandle: "b" }));
    const all = await store.list();
    assert.equal(all.length, 2);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("delete removes the record", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-registry-"));
  const store = new FileLocalRegistryStore(join(dir, "registry.json"));
  try {
    await store.save(makeRecord());
    await store.delete("handle-1");
    const loaded = await store.get("handle-1");
    assert.equal(loaded, null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("survives a process restart (new store instance, same file)", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-registry-"));
  const filePath = join(dir, "registry.json");
  try {
    const storeA = new FileLocalRegistryStore(filePath);
    await storeA.save(makeRecord());

    const storeB = new FileLocalRegistryStore(filePath);
    const loaded = await storeB.get("handle-1");
    assert.ok(loaded);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("toServerMountContext strips canonicalRootPath", () => {
  const record = makeRecord();
  const context = toServerMountContext(record);
  assert.equal("canonicalRootPath" in context, false);
  assert.equal(context.localMountHandle, "handle-1");
  assert.equal(context.deviceId, "device-1");
});
