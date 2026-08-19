import test from "node:test";
import assert from "node:assert/strict";

import { isWatchedPath } from "./filters.js";

test("watches python source files", () => {
  assert.equal(isWatchedPath("src/main.py"), true);
});

test("watches manifest files by exact name", () => {
  assert.equal(isWatchedPath("package.json"), true);
  assert.equal(isWatchedPath("requirements.txt"), true);
});

test("watches doc files", () => {
  assert.equal(isWatchedPath("docs/architecture.md"), true);
});

test("excludes files inside node_modules", () => {
  assert.equal(isWatchedPath("node_modules/pkg/index.js"), false);
});

test("excludes files inside .git", () => {
  assert.equal(isWatchedPath(".git/HEAD"), false);
});

test("excludes hidden directories generically", () => {
  assert.equal(isWatchedPath(".cache/foo.py"), false);
});

test("excludes hidden files", () => {
  assert.equal(isWatchedPath("src/.env"), false);
});

test("excludes editor temp/swap files", () => {
  assert.equal(isWatchedPath("src/main.py.swp"), false);
  assert.equal(isWatchedPath("src/main.py~"), false);
  assert.equal(isWatchedPath("download.crdownload"), false);
});

test("excludes purely numeric filenames (vim 4913-style)", () => {
  assert.equal(isWatchedPath("src/4913"), false);
});

test("excludes unrecognized extensions", () => {
  assert.equal(isWatchedPath("image.png"), false);
});

test("handles windows-style backslash separators", () => {
  assert.equal(isWatchedPath("src\\main.py"), true);
  assert.equal(isWatchedPath("node_modules\\pkg\\index.js"), false);
});
