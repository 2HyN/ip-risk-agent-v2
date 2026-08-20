import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import assert from "node:assert/strict";

import { RootEscapeError, resolveWithinRoot } from "./path-guard.js";

let root: string;
let outside: string;

before(() => {
  root = mkdtempSync(join(tmpdir(), "iprisk-root-"));
  outside = mkdtempSync(join(tmpdir(), "iprisk-outside-"));
  mkdirSync(join(root, "sub"), { recursive: true });
  writeFileSync(join(root, "sub", "file.txt"), "hello");
  writeFileSync(join(outside, "secret.txt"), "nope");
});

after(() => {
  rmSync(root, { recursive: true, force: true });
  rmSync(outside, { recursive: true, force: true });
});

test("allows a path within root", () => {
  const resolved = resolveWithinRoot(root, "sub/file.txt");
  assert.ok(resolved.endsWith(join("sub", "file.txt")));
});

test("allows a not-yet-existing path within root (create event case)", () => {
  const resolved = resolveWithinRoot(root, "sub/new-file.txt");
  assert.ok(resolved.endsWith(join("sub", "new-file.txt")));
});

test("rejects absolute relative_path", () => {
  assert.throws(() => resolveWithinRoot(root, join(outside, "secret.txt")), RootEscapeError);
});

test("rejects dot-dot traversal", () => {
  assert.throws(() => resolveWithinRoot(root, "../outside.txt"), RootEscapeError);
});

test("rejects deep dot-dot traversal", () => {
  assert.throws(() => resolveWithinRoot(root, "sub/../../outside.txt"), RootEscapeError);
});

test("rejects symlink escaping root (skips gracefully if symlink creation is not permitted)", (t) => {
  const linkPath = join(root, "escape-link");
  try {
    symlinkSync(outside, linkPath, "dir");
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "EPERM" || code === "EACCES") {
      t.skip(
        "symlink creation not permitted in this environment (Windows without Developer Mode/admin) - " +
          "run as admin or enable Developer Mode to exercise this test"
      );
      return;
    }
    throw err;
  }

  try {
    assert.throws(() => resolveWithinRoot(root, "escape-link/secret.txt"), RootEscapeError);
  } finally {
    rmSync(linkPath, { force: true });
  }
});
