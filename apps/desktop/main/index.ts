import type {
  AnalysisArtifact,
  AnalysisResult,
  SourceChange,
  SourceSnapshot,
} from "@iprisk/contracts";
export type DesktopContractImportProof = {
  change: SourceChange;
  snapshot: SourceSnapshot;
  artifact: AnalysisArtifact;
  result: AnalysisResult;
};

import { app, BrowserWindow, ipcMain } from "electron";
import { hostname } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { LocalSourceService } from "../core/local-source-service.js";
import { ensureDeviceIdentity, FileDeviceIdentityStore } from "../local-registry/device-identity.js";
import { FileLocalRegistryStore } from "../local-registry/store.js";
import { ElectronArtifactOpener } from "./electron-artifact-opener.js";
import { ElectronDirectoryPicker } from "./electron-directory-picker.js";

const currentDir = dirname(fileURLToPath(import.meta.url));

async function bootstrap(): Promise<void> {
  const userDataDir = app.getPath("userData");
  const registry = new FileLocalRegistryStore(join(userDataDir, "local-mounts.json"));
  const deviceStore = new FileDeviceIdentityStore(join(userDataDir, "device-identity.json"));
  const device = await ensureDeviceIdentity(deviceStore, hostname());

  const service = new LocalSourceService(
    new ElectronDirectoryPicker(),
    registry,
    device,
    new ElectronArtifactOpener()
  );

  ipcMain.handle("chooseTrackedDirectory", () => service.chooseTrackedDirectory());
  ipcMain.handle("connectLocalMount", (_event, params) => service.connectLocalMount(params));
  ipcMain.handle("openTrackedArtifact", (_event, handle: string, relativePath: string) =>
    service.openTrackedArtifact(handle, relativePath)
  );
  ipcMain.handle("showTrackedArtifactInFolder", (_event, handle: string, relativePath: string) =>
    service.showTrackedArtifactInFolder(handle, relativePath)
  );
  ipcMain.handle("getDesktopConnectionStatus", () => service.getDesktopConnectionStatus());

  const window = new BrowserWindow({
    width: 900,
    height: 640,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // preload 스크립트가 ESM(import)을 쓰기 위해 필요 (Electron 공식 문서 권장)
      preload: join(currentDir, "../preload/preload.mjs"),
    },
  });

  const smokeTestHtml = [
    "<h1>IP Risk Agent Desktop</h1>",
    "<p>Phase 3 (Electron wiring) smoke test.</p>",
    '<button id="pick">Choose Tracked Directory</button>',
    '<pre id="result"></pre>',
    "<script>",
    "document.getElementById('pick').addEventListener('click', async () => {",
    "  const r = await window.desktopApi.chooseTrackedDirectory();",
    "  document.getElementById('result').textContent = JSON.stringify(r, null, 2);",
    "});",
    "</script>",
  ].join("");

  void window.loadURL(`data:text/html,${encodeURIComponent(smokeTestHtml)}`);
}

app.whenReady().then(bootstrap);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
