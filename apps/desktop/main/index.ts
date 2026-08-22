import { app, BrowserWindow, ipcMain, safeStorage, shell } from "electron";
import { hostname } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  LocalSourceService,
  type ConnectLocalMountParams,
} from "../core/local-source-service.js";
import { ensureDeviceIdentity, FileDeviceIdentityStore } from "../local-registry/device-identity.js";
import { FileLocalRegistryStore, type LocalMountRecord } from "../local-registry/store.js";
import { EncryptedFileDeviceCredentialStore } from "../security/device-credential-store.js";
import { startLocalWatcher, type LocalWatcherHandle } from "../watcher/watcher.js";
import { DesktopEventReporter, FetchHttpClient } from "./desktop-event-reporter.js";
import { RetryingDesktopEventQueue } from "./desktop-event-queue.js";
import { DeviceEnrollmentClient } from "./device-enrollment-client.js";
import { ElectronArtifactOpener } from "./electron-artifact-opener.js";
import { ElectronDirectoryPicker } from "./electron-directory-picker.js";
import { HttpMountRegistrationClient } from "./mount-registration-client.js";

const currentDir = dirname(fileURLToPath(import.meta.url));
const runtimeProfile = process.env["APP_ENV"] ?? "local";
const serverBaseUrl = trustedApplicationUrl(
  process.env["IPRISK_SERVER_BASE_URL"] ?? "http://127.0.0.1:8000",
  runtimeProfile,
);

async function bootstrap(): Promise<void> {
  const userDataDir = app.getPath("userData");
  const registry = new FileLocalRegistryStore(join(userDataDir, "local-mounts.json"));
  const deviceStore = new FileDeviceIdentityStore(join(userDataDir, "device-identity.json"));
  const credentialStore = new EncryptedFileDeviceCredentialStore(
    join(userDataDir, "device-credential.enc.json"),
    {
      isEncryptionAvailable: () => safeStorage.isEncryptionAvailable(),
      encryptString: (value) => safeStorage.encryptString(value),
      decryptString: (value) => safeStorage.decryptString(Buffer.from(value)),
    },
  );
  const device = await ensureDeviceIdentity(deviceStore, hostname());
  const enrollmentClient = new DeviceEnrollmentClient(serverBaseUrl);
  const httpClient = new FetchHttpClient(serverBaseUrl, credentialStore);
  const mountRegistrationClient = new HttpMountRegistrationClient(httpClient);
  const service = new LocalSourceService(
    new ElectronDirectoryPicker(),
    registry,
    device,
    new ElectronArtifactOpener(),
    mountRegistrationClient,
  );
  const activeWatchers = new Map<string, LocalWatcherHandle>();
  const eventQueues = new Map<string, RetryingDesktopEventQueue>();

  const startWatchingMount = async (record: LocalMountRecord): Promise<void> => {
    if (activeWatchers.has(record.localMountHandle)) return;
    const reporter = new DesktopEventReporter(httpClient, {
      riskWorkspaceId: record.riskWorkspaceId,
      mountId: record.serverMountId,
      sourceWorkspaceId: record.sourceWorkspaceId,
      deviceId: record.deviceId,
    });
    const queue = new RetryingDesktopEventQueue(reporter);
    const handle = await startLocalWatcher(record.canonicalRootPath, (event) => {
      queue.enqueue(event);
    });
    activeWatchers.set(record.localMountHandle, handle);
    eventQueues.set(record.localMountHandle, queue);
  };

  const restoreWatchers = async (): Promise<void> => {
    if ((await credentialStore.getCredential()) === null) return;
    for (const record of await registry.list()) {
      if (record.status === "ACTIVE") await startWatchingMount(record);
    }
  };
  await restoreWatchers();

  ipcMain.handle("chooseTrackedDirectory", () => service.chooseTrackedDirectory());
  ipcMain.handle("enrollDesktopDevice", async (_event, rawChallenge: unknown) => {
    const challenge = boundedString(rawChallenge, "challenge", 32, 512);
    const enrolled = await enrollmentClient.exchange(
      challenge,
      device.deviceId,
      device.deviceLabel,
    );
    await credentialStore.saveCredential(enrolled.deviceCredential);
    await restoreWatchers();
    return desktopStatus(service, credentialStore);
  });
  ipcMain.handle("clearDesktopCredential", async () => {
    for (const watcher of activeWatchers.values()) await watcher.close();
    activeWatchers.clear();
    eventQueues.clear();
    await credentialStore.clear();
    return desktopStatus(service, credentialStore);
  });
  ipcMain.handle("connectLocalMount", async (_event, rawParams: unknown) => {
    const params = connectParams(rawParams);
    const record = await service.connectLocalMount(params);
    await startWatchingMount(record);
    return {
      localMountHandle: record.localMountHandle,
      serverMountId: record.serverMountId,
      sourceWorkspaceId: record.sourceWorkspaceId,
      status: record.status,
    };
  });
  ipcMain.handle("openTrackedArtifact", (_event, rawHandle: unknown, rawPath: unknown) =>
    service.openTrackedArtifact(
      boundedString(rawHandle, "localMountHandle", 1, 256),
      boundedString(rawPath, "relativePath", 1, 4096),
    ),
  );
  ipcMain.handle("showTrackedArtifactInFolder", (_event, rawHandle: unknown, rawPath: unknown) =>
    service.showTrackedArtifactInFolder(
      boundedString(rawHandle, "localMountHandle", 1, 256),
      boundedString(rawPath, "relativePath", 1, 4096),
    ),
  );
  ipcMain.handle("openLocalOriginal", (_event, rawDeviceId: unknown, rawArtifactId: unknown) =>
    service.openLocalOriginal(
      boundedString(rawDeviceId, "deviceId", 1, 256),
      boundedString(rawArtifactId, "sourceArtifactId", 1, 4096),
    ),
  );
  ipcMain.handle("getDesktopConnectionStatus", () => desktopStatus(service, credentialStore));

  const rendererUrl = trustedApplicationUrl(
    process.env["IPRISK_DESKTOP_RENDERER_URL"] ?? `${serverBaseUrl}/app`,
    runtimeProfile,
  );
  if (
    runtimeProfile === "production" &&
    new URL(rendererUrl).origin !== new URL(serverBaseUrl).origin
  ) {
    throw new Error("Production desktop renderer must share the API origin");
  }
  const window = new BrowserWindow({
    width: 1180,
    height: 780,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: join(currentDir, "../preload/preload.cjs"),
    },
  });
  // preload 가 실패하면 Electron 은 renderer 콘솔에만 적고 창은 멀쩡히 뜬다.
  // 그러면 `window.desktopApi` 가 없어 화면이 desktop 을 web 으로 보고 Local
  // Folder 를 잠그는데, 겉으로는 아무 문제도 없어 보인다. 실제로 그 상태를 한참
  // 들여다봤다. 터미널에 남긴다.
  //
  // 경로 전체는 남기지 않는다 — 사용자의 로컬 절대경로다. 파일 이름과 사유만 적는다.
  window.webContents.on("preload-error", (_event, preloadPath, error) => {
    const name = preloadPath.split(/[\/]/u).pop();
    console.error(`preload failed: ${name}: ${error.message}`);
  });

  applyNavigationPolicy(window, rendererUrl, serverBaseUrl);
  await window.loadURL(rendererUrl);
}

async function desktopStatus(
  service: LocalSourceService,
  credentials: EncryptedFileDeviceCredentialStore,
) {
  const status = await service.getDesktopConnectionStatus();
  return { ...status, enrolled: (await credentials.getCredential()) !== null };
}

function connectParams(value: unknown): ConnectLocalMountParams {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("connectLocalMount parameters are invalid");
  }
  const item = value as Record<string, unknown>;
  const allowed = new Set([
    "selectionId",
    "riskWorkspaceId",
    "includePatterns",
    "excludePatterns",
  ]);
  if (Object.keys(item).some((key) => !allowed.has(key))) {
    throw new Error("connectLocalMount contains an unexpected field");
  }
  return {
    selectionId: boundedString(item["selectionId"], "selectionId", 8, 256),
    riskWorkspaceId: boundedString(item["riskWorkspaceId"], "riskWorkspaceId", 1, 256),
    includePatterns: stringList(item["includePatterns"], "includePatterns"),
    excludePatterns: stringList(item["excludePatterns"], "excludePatterns"),
  };
}

function stringList(value: unknown, name: string): string[] {
  if (!Array.isArray(value) || value.length > 100) throw new Error(`${name} is invalid`);
  return value.map((item) => boundedString(item, name, 1, 512));
}

function boundedString(value: unknown, name: string, minimum: number, maximum: number): string {
  if (typeof value !== "string" || value.length < minimum || value.length > maximum) {
    throw new Error(`${name} is invalid`);
  }
  return value;
}

function trustedApplicationUrl(raw: string, profile: string): string {
  const parsed = new URL(raw);
  const loopback = ["127.0.0.1", "localhost", "::1"].includes(parsed.hostname);
  if (parsed.username || parsed.password || (parsed.protocol !== "https:" && !(profile !== "production" && parsed.protocol === "http:" && loopback))) {
    throw new Error("Desktop application URL must be HTTPS or a local loopback development URL");
  }
  return parsed.toString().replace(/\/$/u, "");
}

function applyNavigationPolicy(
  window: BrowserWindow,
  rendererUrl: string,
  apiUrl: string,
): void {
  const allowedOrigins = new Set([
    new URL(rendererUrl).origin,
    new URL(apiUrl).origin,
    "https://accounts.google.com",
    "https://github.com",
  ]);
  window.webContents.on("will-navigate", (event, target) => {
    if (!allowedOrigins.has(new URL(target).origin)) event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    const parsed = new URL(url);
    if (
      parsed.protocol === "https:" &&
      ["drive.google.com", "github.com"].includes(parsed.hostname) &&
      !parsed.username &&
      !parsed.password
    ) {
      void shell.openExternal(parsed.toString());
    }
    return { action: "deny" };
  });
}

app.whenReady().then(() => bootstrap().catch(() => app.quit()));

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
