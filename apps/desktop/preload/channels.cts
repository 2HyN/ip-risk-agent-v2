/**
 * Renderer에 노출할 최소 capability 목록.
 *
 * CommonJS 모듈로 유지하는 이유는 sandboxed Electron preload가 ESM import를
 * 지원하지 않기 때문이다. Product renderer와 preload test도 이 단일 목록을
 * 공유한다.
 */
export const ALLOWED_RENDERER_CHANNELS = [
  "chooseTrackedDirectory",
  "enrollDesktopDevice",
  "clearDesktopCredential",
  "connectLocalMount",
  "openLocalOriginal",
  "openTrackedArtifact",
  "showTrackedArtifactInFolder",
  "getDesktopConnectionStatus",
] as const;

export type AllowedRendererChannel = (typeof ALLOWED_RENDERER_CHANNELS)[number];

export const FORBIDDEN_RENDERER_CHANNELS = [
  "readFile",
  "writeFile",
  "openPath",
  "listDirectory",
  "executeShell",
  "getDeviceCredential",
  "saveDeviceCredential",
] as const;
