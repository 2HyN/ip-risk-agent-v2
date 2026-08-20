/**
 * Master Spec §65 PlatformAdapter. Web과 Electron Desktop 사이의 차이를
 * 이 경계 하나로 흡수한다 — 컴포넌트는 "지금 desktop인지 web인지"를 몰라도
 * 되고, platform.chooseLocalDirectory()만 부르면 된다.
 *
 * DesktopApi 타입은 apps/desktop/preload/api.ts의 ALLOWED_RENDERER_CHANNELS와
 * 반드시 이름이 일치해야 한다 (frontend가 desktop 패키지를 직접 참조하지
 * 않으므로 여기서 shape만 다시 선언한다).
 */

export type Platform = "web" | "desktop";

export interface PlatformAdapter {
  platform: Platform;
  chooseLocalDirectory(): Promise<{ canonicalRootPath: string } | null>;
  openTrackedArtifact(localMountHandle: string, relativePath: string): Promise<void>;
}

interface DesktopApi {
  chooseTrackedDirectory: () => Promise<{ canonicalRootPath: string } | null>;
  connectLocalMount: (params: unknown) => Promise<unknown>;
  openTrackedArtifact: (handle: string, relativePath: string) => Promise<void>;
  showTrackedArtifactInFolder: (handle: string, relativePath: string) => Promise<void>;
  getDesktopConnectionStatus: () => Promise<{ deviceId: string; mountCount: number }>;
}

declare global {
  interface Window {
    desktopApi?: DesktopApi;
  }
}

export class WebPlatformAdapter implements PlatformAdapter {
  readonly platform: Platform = "web";

  async chooseLocalDirectory(): Promise<{ canonicalRootPath: string } | null> {
    // Master Spec §30/§65: Local Folder는 Desktop 전용이다.
    return null;
  }

  async openTrackedArtifact(_localMountHandle: string, _relativePath: string): Promise<void> {
    throw new Error("Local artifacts can only be opened from the Desktop app.");
  }
}

export class ElectronPlatformAdapter implements PlatformAdapter {
  readonly platform: Platform = "desktop";

  constructor(private readonly api: DesktopApi) {}

  async chooseLocalDirectory(): Promise<{ canonicalRootPath: string } | null> {
    return this.api.chooseTrackedDirectory();
  }

  async openTrackedArtifact(localMountHandle: string, relativePath: string): Promise<void> {
    return this.api.openTrackedArtifact(localMountHandle, relativePath);
  }
}

export function detectPlatformAdapter(): PlatformAdapter {
  if (typeof window !== "undefined" && window.desktopApi) {
    return new ElectronPlatformAdapter(window.desktopApi);
  }
  return new WebPlatformAdapter();
}
