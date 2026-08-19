import test from "node:test";
import assert from "node:assert/strict";

import { ALLOWED_RENDERER_CHANNELS, FORBIDDEN_RENDERER_CHANNELS } from "./api.js";

test("allowed list matches Agent2 Spec 34 exactly", () => {
  assert.deepEqual(
    [...ALLOWED_RENDERER_CHANNELS].sort(),
    [
      "chooseTrackedDirectory",
      "connectLocalMount",
      "getDesktopConnectionStatus",
      "openTrackedArtifact",
      "showTrackedArtifactInFolder",
    ].sort()
  );
});

test("forbidden list has zero overlap with allowed list", () => {
  const allowedSet = new Set<string>(ALLOWED_RENDERER_CHANNELS);
  for (const forbidden of FORBIDDEN_RENDERER_CHANNELS) {
    assert.equal(allowedSet.has(forbidden), false, `${forbidden} must never be allowed`);
  }
});
