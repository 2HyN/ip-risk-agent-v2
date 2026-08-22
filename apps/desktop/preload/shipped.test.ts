/**
 * 빌드 산출물에 preload 진입점이 실제로 들어 있는가.
 *
 * `preload.cts` 는 **아무도 import 하지 않는다.** main 이 `BrowserWindow` 설정에서
 * 경로 문자열로만 가리키는 진입점이라, tsconfig 의 `include` 에 빠지면 조용히
 * 빌드에서 사라진다. 타입 검사도 시험도 전부 통과한다 — 그 파일을 아무도 보지
 * 않기 때문이다.
 *
 * 그 결과가 화면에서는 이렇게 나타났다. `contextBridge.exposeInMainWorld` 가 돌지
 * 않아 `window.desktopApi` 가 없고, 화면은 desktop 을 **web 으로 보고 Local Folder
 * 를 잠갔다.** 앱은 멀쩡히 켜지고 서버에도 붙는데 폴더만 연결할 수 없었다.
 *
 * 그래서 산출물 자체를 확인한다. 컴파일된 코드를 읽는 것이 아니라 **있어야 할
 * 파일이 있는지**를 본다.
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import assert from "node:assert/strict";

const distPreload = dirname(fileURLToPath(import.meta.url));

test("preload 진입점이 빌드 산출물에 있다", () => {
  const entry = join(distPreload, "preload.cjs");
  assert.ok(
    existsSync(entry),
    `${entry} 가 없다. tsconfig 의 include 에서 preload/**/*.cts 가 빠지면 ` +
      "이 진입점만 조용히 사라지고, 화면은 desktop 을 web 으로 본다",
  );
});

test("main 이 가리키는 preload 경로와 산출물 위치가 같다", () => {
  // main 은 `join(currentDir, "../preload/preload.cjs")` 를 쓴다. 여기서 보는
  // 위치가 그 경로와 같은 자리인지 확인한다 — 이름만 맞고 자리가 다르면
  // 마찬가지로 다리가 놓이지 않는다.
  const fromMain = join(distPreload, "..", "main", "..", "preload", "preload.cjs");
  assert.ok(existsSync(fromMain), `${fromMain} 가 없다`);
});


test("preload 가 노출하는 채널이 허용 목록과 정확히 같다", async () => {
  // sandbox preload 는 상대 경로 모듈을 부를 수 없어 목록을 안에 적어 두었다.
  // 두 곳에 있는 값이므로 어긋나면 여기서 잡는다 — 한쪽에만 채널을 더하면 화면이
  // 그 기능을 부르지 못하거나, 허용하지 않은 것을 부르게 된다.
  const { ALLOWED_RENDERER_CHANNELS } = await import("./channels.cjs");
  const source = readFileSync(join(distPreload, "preload.cjs"), "utf8");

  const opened = source.indexOf("ALLOWED_RENDERER_CHANNELS = [");
  assert.notEqual(opened, -1, "preload 에서 채널 목록을 찾지 못했다");
  const literal = source.slice(opened, source.indexOf("]", opened));
  const exposed = [...literal.matchAll(/"([^"]+)"/gu)].map((match) => match[1]);

  assert.deepEqual(exposed, [...ALLOWED_RENDERER_CHANNELS]);
});
