/**
 * Renderer 에 노출할 최소 capability 를 놓는 다리.
 *
 * **채널 목록을 여기에 그대로 적는다.** sandbox preload 는 상대 경로 모듈을 부를
 * 수 없다 — `require("./channels.cjs")` 는 `module not found` 로 죽고, Electron 은
 * 그것을 renderer 콘솔에만 적는다. 창은 멀쩡히 뜨고 `window.desktopApi` 만 없어서,
 * 화면은 desktop 을 web 으로 보고 Local Folder 를 잠근다. 겉으로는 아무 문제도
 * 없어 보인다.
 *
 * 목록이 두 곳에 있는 것은 sandbox 를 켜 두기 위해 치르는 값이다. 대신
 * `shipped.test.ts` 가 이 목록과 `channels.cts` 의 것이 같은지 확인하므로,
 * 한쪽만 바뀌면 시험이 깨진다.
 */

import { contextBridge, ipcRenderer } from "electron";

const ALLOWED_RENDERER_CHANNELS = [
  "chooseTrackedDirectory",
  "enrollDesktopDevice",
  "clearDesktopCredential",
  "connectLocalMount",
  "openLocalOriginal",
  "openTrackedArtifact",
  "showTrackedArtifactInFolder",
  "getDesktopConnectionStatus",
] as const;

const api: Record<string, (...args: unknown[]) => Promise<unknown>> = {};
for (const channel of ALLOWED_RENDERER_CHANNELS) {
  api[channel] = (...args: unknown[]) => ipcRenderer.invoke(channel, ...args);
}

contextBridge.exposeInMainWorld("desktopApi", api);
