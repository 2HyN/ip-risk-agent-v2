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

test("첫 훑기에서는 이미 있던 파일도 보고한다", async () => {
  // 폴더를 연결했는데 파일이 하나도 보이지 않던 원인이다. 감시는 준비되기 전의
  // add 를 버리는데(다시 켤 때마다 전부 다시 올라오는 것을 막는다), 처음 붙일
  // 때는 그 규칙 때문에 아무것도 올라가지 않았다.
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "main.py"), "print(1)");
  writeFileSync(join(root, "design.md"), "# 설계\n");
  writeFileSync(join(root, "notes.bin"), "binary");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
    emitExisting: true,
  });

  try {
    await delay(TEST_DEBOUNCE_MS + 400);
    const reported = events.map((event) => event.relativePath).sort();
    // 감시 대상만 올라온다. .bin 은 코드도 문서도 아니다.
    assert.deepEqual(reported, ["design.md", "main.py"]);
    assert.ok(events.every((event) => event.changeType === "CREATE"));
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("다시 켤 때는 이미 있던 파일을 다시 보고하지 않는다", async () => {
  // 켤 때마다 전부 다시 올라오면 같은 내용을 계속 올려 보내게 된다.
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  writeFileSync(join(root, "main.py"), "print(1)");
  await delay(200);

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });

  try {
    await delay(TEST_DEBOUNCE_MS + 400);
    assert.deepEqual(events, []);
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("하위 폴더 파일의 상대 경로는 슬래시로 온다", async () => {
  // Windows 의 path.relative 는 `docs\design.md` 를 준다. 서버는 provider 상대
  // 경로만 받고 역슬래시를 거부하므로, 그대로 보내면 하위 폴더 파일만 422 로
  // 죽는다 — 루트 파일은 구분자가 없어 우연히 통과한다. 실제로 그 상태로
  // 폴더를 붙여 놓고 파일이 하나도 보이지 않았다.
  const root = mkdtempSync(join(tmpdir(), "iprisk-watch-"));
  mkdirSync(join(root, "docs"));
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
  });
  const events: LocalChangeEvent[] = [];

  try {
    writeFileSync(join(root, "docs", "design.md"), "# 설계\n");
    await delay(TEST_DEBOUNCE_MS + 300);

    assert.equal(events.length, 1);
    assert.equal(events[0]?.relativePath, "docs/design.md");
    assert.ok(!events[0]?.relativePath.includes("\\"));
  } finally {
    await handle.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("폴더 밖을 가리키던 링크가 지워져도 그 파일의 삭제를 보고하지 않는다", async () => {
  // 경로 가드는 링크가 살아 있을 때만 탈출을 알아본다. 링크가 지워지면 그 경로는
  // "폴더 안의 없는 경로" 와 구별되지 않아 가드를 그냥 통과한다. 실제로 폴더 밖
  // 파일 두 개가 그렇게 삭제 이벤트로 서버까지 갔다.
  const base = mkdtempSync(join(tmpdir(), "iprisk-escape-"));
  const root = join(base, "inside");
  const outside = join(base, "outside");
  mkdirSync(root);
  mkdirSync(outside);
  writeFileSync(join(outside, "secret.md"), "# 폴더 밖\n");

  const linkPath = join(root, "escape");
  try {
    symlinkSync(outside, linkPath, "junction");
  } catch {
    return; // 링크를 만들 수 없는 환경이면 확인할 것이 없다
  }

  const events: LocalChangeEvent[] = [];
  const handle = await startLocalWatcher(root, (e) => events.push(e), {
    debounceMs: TEST_DEBOUNCE_MS,
    moveCorrelationWindowMs: TEST_MOVE_WINDOW_MS,
    emitExisting: true,
  });

  try {
    await delay(TEST_DEBOUNCE_MS + 300);
    // 링크가 살아 있는 동안에도 폴더 밖 파일은 보고되지 않는다.
    assert.deepEqual(events, []);

    rmSync(linkPath, { recursive: true, force: true });
    await delay(TEST_DEBOUNCE_MS + 400);

    // 링크가 사라진 뒤에도 마찬가지다. 보고한 적 없으면 지운 것도 알리지 않는다.
    assert.equal(events.length, 0, JSON.stringify(events));
  } finally {
    await handle.close();
    rmSync(base, { recursive: true, force: true });
  }
});
