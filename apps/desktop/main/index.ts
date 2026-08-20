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
import { FileLocalRegistryStore, type LocalMountRecord } from "../local-registry/store.js";
import { startLocalWatcher, type LocalWatcherHandle } from "../watcher/watcher.js";
import { DesktopEventReporter, FetchHttpClient } from "./desktop-event-reporter.js";
import { ElectronArtifactOpener } from "./electron-artifact-opener.js";
import { ElectronDirectoryPicker } from "./electron-directory-picker.js";
import { HttpMountRegistrationClient } from "./mount-registration-client.js";

const currentDir = dirname(fileURLToPath(import.meta.url));

const SERVER_BASE_URL = process.env["IPRISK_SERVER_BASE_URL"] ?? "http://localhost:8000";

async function bootstrap(): Promise<void> {
  const userDataDir = app.getPath("userData");
  const registry = new FileLocalRegistryStore(join(userDataDir, "local-mounts.json"));
  const deviceStore = new FileDeviceIdentityStore(join(userDataDir, "device-identity.json"));
  const device = await ensureDeviceIdentity(deviceStore, hostname());

  const httpClient = new FetchHttpClient(SERVER_BASE_URL);
  const mountRegistrationClient = new HttpMountRegistrationClient(httpClient);

  // 앱이 뜰 때마다 이 컴퓨터를 서버에 등록해둔다 (device_id를 app_user에
  // 연결하는 건 서버 콜백 몫 — 우리는 호출만 한다).
  try {
    await mountRegistrationClient.registerDevice(device.deviceId, device.deviceLabel);
  } catch (err) {
    console.error("failed to register this device with the server:", err);
  }

  const service = new LocalSourceService(
    new ElectronDirectoryPicker(),
    registry,
    device,
    new ElectronArtifactOpener(),
    mountRegistrationClient
  );

  const activeWatchers = new Map<string, LocalWatcherHandle>();

  const startWatchingMount = async (record: LocalMountRecord): Promise<void> => {
    if (activeWatchers.has(record.localMountHandle)) {
      return;
    }
    const reporter = new DesktopEventReporter(httpClient, {
      riskWorkspaceId: record.riskWorkspaceId,
      mountId: record.localMountHandle,
      sourceWorkspaceId: record.sourceWorkspaceId,
      deviceId: record.deviceId,
    });
    const handle = await startLocalWatcher(record.canonicalRootPath, (event) => {
      reporter.report(event).catch((err: unknown) => {
        console.error(`failed to report local change for ${record.localMountHandle}:`, err);
      });
    });
    activeWatchers.set(record.localMountHandle, handle);
  };

  // 앱 재시작 후에도 이미 연결돼있던 mount들은 계속 감시를 이어간다.
  for (const record of await registry.list()) {
    if (record.status === "ACTIVE") {
      await startWatchingMount(record);
    }
  }

  ipcMain.handle("chooseTrackedDirectory", () => service.chooseTrackedDirectory());
  ipcMain.handle("connectLocalMount", async (_event, params) => {
    const record = await service.connectLocalMount(params);
    await startWatchingMount(record);
    return record;
  });
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
      sandbox: false,
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
