import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import assert from "node:assert/strict";

import type { LocalChangeEvent } from "./watcher.js";
import { startLocalWatcher } from "./watcher.js";

const TEST_DEBOUNCE_MS = 80;

test("emits CREATE for a new watched file", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), { debounceMs: TEST_DEBOUNCE_MS });

  try {
    writeFileSync(join(root, "main.py"), "print(1)");
    await delay(TEST_DEBOUNCE_MS + 200);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.changeType, "CREATE");
    assert.equal(events[0]?.relativePath, "main.py");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("emits UPDATE for a modified watched file", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "main.py"), "print(1)");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), { debounceMs: TEST_DEBOUNCE_MS });

  try {
    writeFileSync(join(root, "main.py"), "print(2)");
    await delay(TEST_DEBOUNCE_MS + 200);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.changeType, "UPDATE");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("emits DELETE for a removed watched file", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "main.py"), "print(1)");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), { debounceMs: TEST_DEBOUNCE_MS });

  try {
    rmSync(join(root, "main.py"));
    await delay(TEST_DEBOUNCE_MS + 200);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.changeType, "DELETE");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("ignores files inside node_modules", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), { debounceMs: TEST_DEBOUNCE_MS });

  try {
    const nm = join(root, "node_modules");
    mkdirSync(nm, { recursive: true });
    writeFileSync(join(nm, "pkg.js"), "module.exports = {}");
    await delay(TEST_DEBOUNCE_MS + 200);

    assert.equal(events.length, 0);
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("debounces rapid successive writes into a single UPDATE", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "main.py"), "v0");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), { debounceMs: TEST_DEBOUNCE_MS });

  try {
    writeFileSync(join(root, "main.py"), "v1");
    await delay(10);
    writeFileSync(join(root, "main.py"), "v2");
    await delay(10);
    writeFileSync(join(root, "main.py"), "v3");
    await delay(TEST_DEBOUNCE_MS + 200);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.changeType, "UPDATE");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("rejects events for symlinked paths escaping root (skips gracefully if unsupported)", async (t) => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  const outside = mkdtempSync(join(tmpdir(), "iprisk-watch-outside-"));

  let linked = true;
  try {
    symlinkSync(outside, join(root, "escape"), "dir");
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "EPERM" || code === "EACCES") {
      t.skip("symlink creation not permitted in this environment");
      linked = false;
    } else {
      throw err;
    }
  }
  if (!linked) {
    rmSync(root, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
    return;
  }

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), { debounceMs: TEST_DEBOUNCE_MS });

  try {
    writeFileSync(join(outside, "escaped.py"), "print('should not be seen')");
    await delay(TEST_DEBOUNCE_MS + 300);

    assert.equal(events.length, 0);
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});
