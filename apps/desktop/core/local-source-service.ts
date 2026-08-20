/**
 * Local Desktop의 핵심 오케스트레이션 로직. Electron API(dialog/shell)를
 * 직접 부르지 않고 포트(DirectoryPicker/ArtifactOpener)로 주입받는다 —
 * 그래서 진짜 Electron 실행 없이 지금 바로 테스트할 수 있다. 실제 Electron
 * 구현은 main/electron-*.ts의 얇은 어댑터가 담당한다.
 */

import { randomUUID } from "node:crypto";
import { realpathSync } from "node:fs";

import {
  resolveTrackedArtifactPath,
  TrackedArtifactNotFoundError,
} from "../local-registry/artifact-resolver.js";
import type { DesktopDevice } from "../local-registry/device-identity.js";
import type { LocalMountRecord, LocalRegistryStore } from "../local-registry/store.js";

export interface DirectoryPicker {
  pickDirectory(): Promise<string | null>;
}

export interface ArtifactOpener {
  openPath(absolutePath: string): Promise<string>;
  showInFolder(absolutePath: string): void;
}

export interface ConnectLocalMountParams {
  canonicalRootPath: string;
  serverMountId: string;
  riskWorkspaceId: string;
  sourceWorkspaceId: string;
  includePatterns: string[];
  excludePatterns: string[];
}

export interface DesktopConnectionStatus {
  deviceId: string;
  mountCount: number;
}

export class LocalMountHandleGenerator {
  generate(): string {
    return randomUUID();
  }
}

export class LocalSourceService {
  constructor(
    private readonly picker: DirectoryPicker,
    private readonly registry: LocalRegistryStore,
    private readonly device: DesktopDevice,
    private readonly opener: ArtifactOpener,
    private readonly handleGenerator: LocalMountHandleGenerator = new LocalMountHandleGenerator()
  ) {}

  async chooseTrackedDirectory(): Promise<{ canonicalRootPath: string } | null> {
    const picked = await this.picker.pickDirectory();
    if (!picked) {
      return null;
    }
    return { canonicalRootPath: realpathSync(picked) };
  }

  async connectLocalMount(params: ConnectLocalMountParams): Promise<LocalMountRecord> {
    const record: LocalMountRecord = {
      localMountHandle: this.handleGenerator.generate(),
      serverMountId: params.serverMountId,
      canonicalRootPath: params.canonicalRootPath,
      deviceId: this.device.deviceId,
      riskWorkspaceId: params.riskWorkspaceId,
      sourceWorkspaceId: params.sourceWorkspaceId,
      includePatterns: params.includePatterns,
      excludePatterns: params.excludePatterns,
      status: "ACTIVE",
    };
    await this.registry.save(record);
    return record;
  }

  async openTrackedArtifact(localMountHandle: string, relativePath: string): Promise<void> {
    const absolutePath = await resolveTrackedArtifactPath(this.registry, localMountHandle, relativePath);
    const errorMessage = await this.opener.openPath(absolutePath);
    if (errorMessage) {
      throw new Error(`failed to open artifact: ${errorMessage}`);
    }
  }

  async showTrackedArtifactInFolder(localMountHandle: string, relativePath: string): Promise<void> {
    const absolutePath = await resolveTrackedArtifactPath(this.registry, localMountHandle, relativePath);
    this.opener.showInFolder(absolutePath);
  }

  async getDesktopConnectionStatus(): Promise<DesktopConnectionStatus> {
    const mounts = await this.registry.list();
    return { deviceId: this.device.deviceId, mountCount: mounts.length };
  }
}

export { TrackedArtifactNotFoundError };
