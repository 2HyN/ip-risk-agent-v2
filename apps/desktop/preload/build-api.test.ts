import test from "node:test";
import assert from "node:assert/strict";

import { ALLOWED_RENDERER_CHANNELS } from "./api.js";
import { buildApiMap } from "./build-api.js";

test("exposed api keys exactly match the allowed channel list", () => {
  const api = buildApiMap(async () => "ok");
  assert.deepEqual(Object.keys(api).sort(), [...ALLOWED_RENDERER_CHANNELS].sort());
});

test("calling an exposed function invokes the underlying channel with the same args", async () => {
  const calls: Array<{ channel: string; args: unknown[] }> = [];
  const api = buildApiMap(async (channel, ...args) => {
    calls.push({ channel, args });
    return "result";
  });

  const result = await api["openTrackedArtifact"]?.("handle-1", "src/a.py");

  assert.equal(result, "result");
  assert.deepEqual(calls, [{ channel: "openTrackedArtifact", args: ["handle-1", "src/a.py"] }]);
});
