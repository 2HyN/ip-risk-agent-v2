import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  isDeniedByIpriskignore,
  loadIpriskignorePatterns,
  parseIpriskignore,
} from "./ipriskignore.js";

test("parseIpriskignore ignores blank lines and comments", () => {
  const content = "\n# comment\n\ncustomer-data/**\n\n# another\n*.pem\n";
  const patterns = parseIpriskignore(content);
  assert.deepEqual(patterns, ["customer-data/**", "*.pem"]);
});

test("isDeniedByIpriskignore matches glob pattern", () => {
  assert.equal(isDeniedByIpriskignore("customer-data/file.csv", ["customer-data/**"]), true);
});

test("isDeniedByIpriskignore no match", () => {
  assert.equal(isDeniedByIpriskignore("src/main.py", ["customer-data/**"]), false);
});

test("isDeniedByIpriskignore empty patterns never denies", () => {
  assert.equal(isDeniedByIpriskignore("anything.py", []), false);
});

test("loadIpriskignorePatterns reads the file at the root when present", () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-ignore-"));
  try {
    writeFileSync(join(root, ".ipriskignore"), "secrets/**\n*.pem\n");
    const patterns = loadIpriskignorePatterns(root);
    assert.deepEqual(patterns, ["secrets/**", "*.pem"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("loadIpriskignorePatterns returns empty array when file is absent", () => {
  const root = mkdtempSync(join(tmpdir(), "iprisk-ignore-"));
  try {
    const patterns = loadIpriskignorePatterns(root);
    assert.deepEqual(patterns, []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
