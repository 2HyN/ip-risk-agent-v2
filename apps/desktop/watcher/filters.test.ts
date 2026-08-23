import test from "node:test";
import assert from "node:assert/strict";

import { isWatchedPath } from "./filters.js";

test("watches python source files", () => {
  assert.equal(isWatchedPath("src/main.py"), true);
});

test("의존성 선언을 감시한다", () => {
  // 예전에는 이 파일들을 뺐다 — "License 판별을 크게 손볼 예정" 이라는 이유였다.
  // 그동안 **Local 마운트는 라이선스 위험을 하나도 만들지 못했다.** 0 단계와 2 단계가
  // 끝나 그 이유가 사라졌다.
  //
  // 라이선스 경로는 KIPRIS 를 쓰지 않으므로 특허 한도가 들지 않는다.
  for (const name of [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.cfg",
    "package-lock.json",
    "uv.lock",
    "poetry.lock",
    "constraints.txt",
  ]) {
    assert.equal(isWatchedPath(name), true, name);
  }
});

test("0-J 가 되살린 이름도 함께 본다", () => {
  // 서버는 이것들을 의존성으로 알아보는데 데스크톱이 감시하지 않으면, Local 에서는
  // 그 파일이 **존재하지 않는다.** 감시가 먼저 거르기 때문이다.
  assert.equal(isWatchedPath("requirements-dev.txt"), true);
  assert.equal(isWatchedPath("requirements.lock"), true);
  assert.equal(isWatchedPath("requirements/base.txt"), true);
  assert.equal(isWatchedPath("requirements/prod.in"), true);
});

test("라이선스 전문은 보지 않는다", () => {
  // 어느 분석기도 맡지 않으므로 감시해 봐야 거부된 artifact 만 남는다 (결함 26).
  for (const name of ["LICENSE", "LICENSE.txt", "LICENCE.md", "NOTICE", "COPYING"]) {
    assert.equal(isWatchedPath(name), false, name);
  }
});

test("의존성처럼 보이지만 아닌 이름은 그대로 본다", () => {
  // 앞부분이 겹친다고 막으면 멀쩡한 문서가 사라진다.
  assert.equal(isWatchedPath("docs/requirements-analysis.md"), true);
  assert.equal(isWatchedPath("setup.py"), true);
  assert.equal(isWatchedPath("README.md"), true);
});

test("서버가 넓힌 확장자를 함께 본다", () => {
  // 서버 표를 넓혀도 데스크톱이 안 보내면 Local 에서는 아무것도 달라지지 않는다.
  for (const name of ["conf/app.yaml", "data/rows.csv", "app.rb", "deploy.sh", "q.sql"]) {
    assert.equal(isWatchedPath(name), true, name);
  }
});

test("빌드 산출물을 넓게 걸러 낸다", () => {
  // KIPRIS 는 월 1,000 회다. 특허 경로 파일 하나가 최대 11 회를 쓴다.
  for (const path of [
    "dist/bundle.js",
    "build/out.py",
    "target/main.rs",
    "vendor/lib.go",
    "node_modules/pkg/index.js",
  ]) {
    assert.equal(isWatchedPath(path), false, path);
  }
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
