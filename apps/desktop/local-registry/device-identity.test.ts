import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { ensureDeviceIdentity, FileDeviceIdentityStore } from "./device-identity.js";

test("creates a new device identity when none exists", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-device-"));
  const store = new FileDeviceIdentityStore(join(dir, "device.json"));
  try {
    const device = await ensureDeviceIdentity(store, "Alice-MacBook");
    assert.ok(device.deviceId.length > 0);
    assert.equal(device.deviceLabel, "Alice-MacBook");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("reuses the same device_id across calls (stability)", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-device-"));
  const store = new FileDeviceIdentityStore(join(dir, "device.json"));
  try {
    const first = await ensureDeviceIdentity(store, "Alice-MacBook");
    const second = await ensureDeviceIdentity(store, "Alice-MacBook");
    assert.equal(first.deviceId, second.deviceId);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("reuses the same device_id across process restarts (new store instance)", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-device-"));
  const filePath = join(dir, "device.json");
  try {
    const storeA = new FileDeviceIdentityStore(filePath);
    const first = await ensureDeviceIdentity(storeA, "Alice-MacBook");

    const storeB = new FileDeviceIdentityStore(filePath);
    const second = await ensureDeviceIdentity(storeB, "Alice-MacBook");

    assert.equal(first.deviceId, second.deviceId);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("updates lastSeen on repeated calls", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-device-"));
  const store = new FileDeviceIdentityStore(join(dir, "device.json"));
  try {
    const first = await ensureDeviceIdentity(store, "Alice-MacBook");
    await new Promise((resolve) => setTimeout(resolve, 5));
    const second = await ensureDeviceIdentity(store, "Alice-MacBook");
    assert.notEqual(first.lastSeen, second.lastSeen);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
