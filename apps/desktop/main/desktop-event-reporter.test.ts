import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import type { LocalChangeEvent } from "../watcher/watcher.js";
import type { HttpClient } from "./desktop-event-reporter.js";
import { DesktopEventReporter } from "./desktop-event-reporter.js";

class FakeHttpClient implements HttpClient {
  calls: Array<{ path: string; body: unknown }> = [];
  stagingObjectName = "staged-object-1";

  async postJson(path: string, body: unknown): Promise<unknown> {
    this.calls.push({ path, body });
    if (path === "/desktop/staging") {
      return { object_name: this.stagingObjectName };
    }
    return { status: "ok", event_id: "fake-event-id" };
  }
}

function config() {
  return {
    riskWorkspaceId: "rw1",
    mountId: "mount-1",
    sourceWorkspaceId: "sw1",
    deviceId: "dev-1",
  };
}

test("CREATE event uploads content then reports the event with the staging object name", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-reporter-"));
  try {
    const filePath = join(root, "main.py");
    writeFileSync(filePath, "print(1)");

    const http = new FakeHttpClient();
    const reporter = new DesktopEventReporter(http, config());

    const event: LocalChangeEvent = { relativePath: "main.py", changeType: "CREATE", absolutePath: filePath };
    await reporter.report(event);

    assert.equal(http.calls.length, 2);
    assert.equal(http.calls[0]?.path, "/desktop/staging");
    assert.deepEqual(http.calls[0]?.body, { mount_id: "mount-1", content: "print(1)" });
    assert.equal(http.calls[1]?.path, "/desktop/events");
    const eventBody = http.calls[1]?.body as Record<string, unknown>;
    assert.equal(eventBody["change_type"], "CREATE");
    assert.equal(eventBody["staging_object_name"], "staged-object-1");
    assert.equal(eventBody["relative_path"], "main.py");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("DELETE event skips staging upload entirely", async () => {
  const http = new FakeHttpClient();
  const reporter = new DesktopEventReporter(http, config());

  const event: LocalChangeEvent = {
    relativePath: "gone.py",
    changeType: "DELETE",
    absolutePath: "/tmp/does-not-matter/gone.py",
  };
  await reporter.report(event);

  assert.equal(http.calls.length, 1);
  assert.equal(http.calls[0]?.path, "/desktop/events");
  const body = http.calls[0]?.body as Record<string, unknown>;
  assert.equal(body["change_type"], "DELETE");
  assert.equal(body["staging_object_name"], undefined);
});

test("MOVE event includes previous_relative_path", async () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-reporter-"));
  try {
    const filePath = join(root, "new_name.py");
    writeFileSync(filePath, "print('moved')");

    const http = new FakeHttpClient();
    const reporter = new DesktopEventReporter(http, config());

    const event: LocalChangeEvent = {
      relativePath: "new_name.py",
      changeType: "MOVE",
      absolutePath: filePath,
      previousRelativePath: "old_name.py",
    };
    await reporter.report(event);

    const eventBody = http.calls[1]?.body as Record<string, unknown>;
    assert.equal(eventBody["change_type"], "MOVE");
    assert.equal(eventBody["previous_relative_path"], "old_name.py");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("silently ignores a file that disappeared before it could be read", async () => {
  const http = new FakeHttpClient();
  const reporter = new DesktopEventReporter(http, config());

  const event: LocalChangeEvent = {
    relativePath: "vanished.py",
    changeType: "CREATE",
    absolutePath: "/tmp/definitely-does-not-exist-anywhere/vanished.py",
  };
  await reporter.report(event);

  assert.equal(http.calls.length, 0);
});

test("내용 해시를 판본으로 함께 보낸다", async () => {
  // Local 에는 provider 판본이 없다. 아무것도 보내지 않으면 서버가 변경을 거절
  // 한다 — 데스크톱이 보낸 이벤트가 전부 그렇게 422 로 죽었다.
  //
  // staging 객체 이름은 올릴 때마다 무작위라 그 자리를 대신할 수 없다. 내용
  // 해시여야 같은 내용이 같은 판본으로 수렴해 중복이 걸러진다.
  const root = mkdtempSync(join(tmpdir(), "iprisk-reporter-"));
  try {
    const filePath = join(root, "main.py");
    writeFileSync(filePath, "print(1)");

    const http = new FakeHttpClient();
    const reporter = new DesktopEventReporter(http, config());

    await reporter.report({
      relativePath: "main.py",
      changeType: "CREATE",
      absolutePath: filePath,
      contentHash: "sha256-of-print-1",
    });

    const eventBody = http.calls[1]?.body as Record<string, unknown>;
    assert.equal(eventBody["revision"], "sha256-of-print-1");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
