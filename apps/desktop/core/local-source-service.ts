/**
 * Local Desktop의 핵심 오케스트레이션 로직. Electron API(dialog/shell)를
 * 직접 부르지 않고 포트(DirectoryPicker/ArtifactOpener)로 주입받는다 —
 * 그래서 진짜 Electron 실행 없이 지금 바로 테스트할 수 있다. 실제 Electron
 * 구현은 main/electron-*.ts의 얇은 어댑터가 담당한다.
 */

import { randomUUID } from "node:crypto";
import { realpathSync } from "node:fs";
import { basename } from "node:path";

import {
  resolveTrackedArtifactPath,
  TrackedArtifactNotFoundError,
} from "../local-registry/artifact-resolver.js";
import type { DesktopDevice } from "../local-registry/device-identity.js";
import type { LocalMountRecord, LocalRegistryStore } from "../local-registry/store.js";
import type { MountRegistrationClient } from "../main/mount-registration-client.js";
import { decodeLocalArtifactId } from "./local-artifact-identity.js";

export interface DirectoryPicker {
  pickDirectory(): Promise<string | null>;
}

export interface ArtifactOpener {
  /** 성공하면 빈 문자열, 실패하면 에러 메시지를 반환한다 (Electron shell.openPath와 동일한 계약). */
  openPath(absolutePath: string): Promise<string>;
  showInFolder(absolutePath: string): void;
}

export interface ConnectLocalMountParams {
  selectionId: string;
  riskWorkspaceId: string;
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
  private readonly pendingSelections = new Map<string, string>();

  constructor(
    private readonly picker: DirectoryPicker,
    private readonly registry: LocalRegistryStore,
    private readonly device: DesktopDevice,
    private readonly opener: ArtifactOpener,
    private readonly mountRegistrationClient: MountRegistrationClient,
    private readonly handleGenerator: LocalMountHandleGenerator = new LocalMountHandleGenerator()
  ) {}

  async chooseTrackedDirectory(): Promise<{ selectionId: string; displayName: string } | null> {
    const picked = await this.picker.pickDirectory();
    if (!picked) {
      return null;
    }
    const canonicalRootPath = realpathSync(picked);
    const selectionId = this.handleGenerator.generate();
    this.pendingSelections.set(selectionId, canonicalRootPath);
    return { selectionId, displayName: basename(canonicalRootPath) };
  }

  async connectLocalMount(params: ConnectLocalMountParams): Promise<LocalMountRecord> {
    const canonicalRootPath = this.pendingSelections.get(params.selectionId);
    if (canonicalRootPath === undefined) {
      throw new Error("unknown or consumed local directory selection");
    }
    // 1단계: 서버에 등록 요청 -> server_mount_id/source_workspace_id 발급받음.
    const { serverMountId, sourceWorkspaceId } = await this.mountRegistrationClient.registerMount({
      riskWorkspaceId: params.riskWorkspaceId,
      deviceId: this.device.deviceId,
      includePatterns: params.includePatterns,
      excludePatterns: params.excludePatterns,
    });

    // 2단계: 발급받은 값으로 로컬에 저장 + 감시 준비.
    const record: LocalMountRecord = {
      localMountHandle: this.handleGenerator.generate(),
      serverMountId,
      canonicalRootPath,
      deviceId: this.device.deviceId,
      riskWorkspaceId: params.riskWorkspaceId,
      sourceWorkspaceId,
      includePatterns: params.includePatterns,
      excludePatterns: params.excludePatterns,
      status: "ACTIVE",
    };
    await this.registry.save(record);
    this.pendingSelections.delete(params.selectionId);
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

  async openLocalOriginal(deviceId: string, sourceArtifactId: string): Promise<void> {
    const identity = decodeLocalArtifactId(sourceArtifactId);
    if (identity.deviceId !== deviceId || identity.deviceId !== this.device.deviceId) {
      throw new Error("local original belongs to another device");
    }
    const record = (await this.registry.list()).find(
      (item) => item.serverMountId === identity.mountId && item.deviceId === deviceId,
    );
    if (record === undefined) {
      throw new Error("local mount is not registered on this desktop");
    }
    await this.openTrackedArtifact(record.localMountHandle, identity.relativePath);
  }

  async getDesktopConnectionStatus(): Promise<DesktopConnectionStatus> {
    const mounts = await this.registry.list();
    return { deviceId: this.device.deviceId, mountCount: mounts.length };
  }
}

export { TrackedArtifactNotFoundError };
