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
