/**
 * Agent 2 Spec 25번 LocalMountRecord + 저장소.
 * 이 storage는 OS user profile/private app data 영역에 둔다 (실제 경로
 * 결정은 Electron main에서 app.getPath('userData') 기준으로 주입).
 * canonical_root_path는 절대 Cloud Contract로 내보내지 않는다 —
 * toServerMountContext()가 그 경계를 코드로 강제한다.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

export type LocalMountStatus = "ACTIVE" | "PAUSED" | "ERROR";

export interface LocalMountRecord {
  localMountHandle: string;
  serverMountId: string;
  canonicalRootPath: string;
  deviceId: string;
  includePatterns: string[];
  excludePatterns: string[];
  status: LocalMountStatus;
}

export interface ServerMountContext {
  localMountHandle: string;
  deviceId: string;
  includePatterns: string[];
  excludePatterns: string[];
}

export function toServerMountContext(record: LocalMountRecord): ServerMountContext {
  return {
    localMountHandle: record.localMountHandle,
    deviceId: record.deviceId,
    includePatterns: record.includePatterns,
    excludePatterns: record.excludePatterns,
  };
}

export interface LocalRegistryStore {
  save(record: LocalMountRecord): Promise<void>;
  get(localMountHandle: string): Promise<LocalMountRecord | null>;
  list(): Promise<LocalMountRecord[]>;
  delete(localMountHandle: string): Promise<void>;
}

export class FileLocalRegistryStore implements LocalRegistryStore {
  constructor(private readonly filePath: string) {}

  private async readAll(): Promise<Record<string, LocalMountRecord>> {
    try {
      const raw = await readFile(this.filePath, "utf-8");
      return JSON.parse(raw) as Record<string, LocalMountRecord>;
    } catch {
      return {};
    }
  }

  private async writeAll(data: Record<string, LocalMountRecord>): Promise<void> {
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(data, null, 2), "utf-8");
  }

  async save(record: LocalMountRecord): Promise<void> {
    const all = await this.readAll();
    all[record.localMountHandle] = record;
    await this.writeAll(all);
  }

  async get(localMountHandle: string): Promise<LocalMountRecord | null> {
    const all = await this.readAll();
    return all[localMountHandle] ?? null;
  }

  async list(): Promise<LocalMountRecord[]> {
    const all = await this.readAll();
    return Object.values(all);
  }

  async delete(localMountHandle: string): Promise<void> {
    const all = await this.readAll();
    delete all[localMountHandle];
    await this.writeAll(all);
  }
}
