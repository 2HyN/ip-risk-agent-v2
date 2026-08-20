/**
 * Agent 2 Spec 34번: Renderer에 노출할 최소 capability 목록.
 * 이 파일은 계약(contract) 그 자체다 — main/preload/renderer 어디서든
 * 이 목록 밖의 이름을 노출하면 안 된다.
 */

export const ALLOWED_RENDERER_CHANNELS = [
  "chooseTrackedDirectory",
  "connectLocalMount",
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
] as const;
