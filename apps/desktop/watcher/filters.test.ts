import test from "node:test";
import assert from "node:assert/strict";

import { isWatchedPath } from "./filters.js";

test("watches python source files", () => {
  assert.equal(isWatchedPath("src/main.py"), true);
});

test("License 대상은 지금 Local 에서 보지 않는다", () => {
  // License 판별을 크게 손볼 예정이라 그때까지 Local 은 코드와 문서만 본다.
  // GitHub 과 Drive 는 그대로 License 검사를 받는다.
  for (const name of [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.cfg",
    "package-lock.json",
    "uv.lock",
    "poetry.lock",
    "LICENSE",
    "NOTICE",
  ]) {
    assert.equal(isWatchedPath(name), false, name);
  }
});

test("이름만 다른 의존성 파일도 함께 빠진다", () => {
  // 이름 목록으로 막으면 requirements.txt 만 걸리고 requirements-dev.txt 는
  // .txt 확장자로 그대로 통과한다. 서버의 표와 같은 판정이어야 한다.
  assert.equal(isWatchedPath("requirements-dev.txt"), false);
  assert.equal(isWatchedPath("requirements/prod.in"), false);
  assert.equal(isWatchedPath("deps/requirements-test.txt"), false);
});

test("의존성처럼 보이지만 아닌 이름은 그대로 본다", () => {
  // 앞부분이 겹친다고 막으면 멀쩡한 문서가 사라진다.
  assert.equal(isWatchedPath("docs/requirements-analysis.md"), true);
  assert.equal(isWatchedPath("setup.py"), true);
  assert.equal(isWatchedPath("README.md"), true);
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
