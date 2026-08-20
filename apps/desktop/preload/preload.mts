import { contextBridge, ipcRenderer } from "electron";

import { buildApiMap } from "./build-api.js";

contextBridge.exposeInMainWorld("desktopApi", buildApiMap(ipcRenderer.invoke.bind(ipcRenderer)));
