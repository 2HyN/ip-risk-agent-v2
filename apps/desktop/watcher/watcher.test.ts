import { mkdirSync, mkdtempSync, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import assert from "node:assert/strict";

import type { LocalChangeEvent } from "./watcher.js";
import { startLocalWatcher } from "./watcher.js";

const TEST_DEBOUNCE_MS = 80;
const TEST_MOVE_WINDOW_MS = 150;

test("emits CREATE for a new watched file", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

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
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

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

test("emits DELETE for a removed watched file with no matching CREATE", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "main.py"), "print(1)");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

  try {
    rmSync(join(root, "main.py"));
    await delay(TEST_DEBOUNCE_MS + TEST_MOVE_WINDOW_MS + 300);

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
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

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
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

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
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

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

test("renaming a file emits a single MOVE event, not DELETE+CREATE", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "old_name.py"), "print('same content')");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

  try {
    renameSync(join(root, "old_name.py"), join(root, "new_name.py"));
    await delay(TEST_DEBOUNCE_MS + TEST_MOVE_WINDOW_MS + 400);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.changeType, "MOVE");
    assert.equal(events[0]?.relativePath, "new_name.py");
    assert.equal(events[0]?.previousRelativePath, "old_name.py");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("deleting a file with no corresponding create still emits DELETE within the correlation window", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "gone.py"), "unique content for this test");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

  try {
    rmSync(join(root, "gone.py"));
    await delay(TEST_DEBOUNCE_MS + TEST_MOVE_WINDOW_MS + 300);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.changeType, "DELETE");
    assert.equal(events[0]?.relativePath, "gone.py");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("delete followed by create of unrelated content does not get merged into MOVE", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "old.py"), "content A");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

  try {
    rmSync(join(root, "old.py"));
    await delay(20);
    writeFileSync(join(root, "new.py"), "totally different content B");
    await delay(TEST_DEBOUNCE_MS + TEST_MOVE_WINDOW_MS + 400);

    const types = events.map((e) => e.changeType).sort();
    assert.deepEqual(types, ["CREATE", "DELETE"]);
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("respects source-level .ipriskignore for newly created files", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, ".ipriskignore"), "secrets/**\n");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

  try {
    mkdirSync(join(root, "secrets"), { recursive: true });
    writeFileSync(join(root, "secrets", "key.pem"), "-----BEGIN KEY-----");
    writeFileSync(join(root, "src.py"), "print(1)");
    await delay(TEST_DEBOUNCE_MS + 300);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.relativePath, "src.py");
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});
