import { contextBridge, ipcRenderer } from "electron";

import { ALLOWED_RENDERER_CHANNELS } from "./channels.cjs";

const api: Record<string, (...args: unknown[]) => Promise<unknown>> = {};
for (const channel of ALLOWED_RENDERER_CHANNELS) {
  api[channel] = (...args: unknown[]) => ipcRenderer.invoke(channel, ...args);
}

contextBridge.exposeInMainWorld("desktopApi", api);
