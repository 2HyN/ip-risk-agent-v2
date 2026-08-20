/**
 * Renderer에 노출할 API 객체를 만드는 순수 로직. ALLOWED_RENDERER_CHANNELS를
 * 그대로 순회해서 만들기 때문에, 허용 목록과 실제로 노출되는 채널이
 * 구조적으로 어긋날 수 없다.
 */

import { ALLOWED_RENDERER_CHANNELS } from "./api.js";

export type InvokeFn = (channel: string, ...args: unknown[]) => Promise<unknown>;

export function buildApiMap(invoke: InvokeFn): Record<string, (...args: unknown[]) => Promise<unknown>> {
  const api: Record<string, (...args: unknown[]) => Promise<unknown>> = {};
  for (const channel of ALLOWED_RENDERER_CHANNELS) {
    api[channel] = (...args: unknown[]) => invoke(channel, ...args);
  }
  return api;
}
