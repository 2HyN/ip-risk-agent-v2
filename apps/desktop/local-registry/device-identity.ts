/**
 * Agent 2 Spec 36번 DesktopDevice. device_id는 random stable UUID —
 * 한 번 생성되면 이 컴퓨터에서 계속 재사용된다 (앱 재시작해도 동일).
 */

import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

export interface DesktopDevice {
  deviceId: string;
  deviceLabel: string;
  lastSeen: string;
}

export interface DeviceIdentityStore {
  load(): Promise<DesktopDevice | null>;
  save(device: DesktopDevice): Promise<void>;
}

export class FileDeviceIdentityStore implements DeviceIdentityStore {
  constructor(private readonly filePath: string) {}

  async load(): Promise<DesktopDevice | null> {
    try {
      const raw = await readFile(this.filePath, "utf-8");
      return JSON.parse(raw) as DesktopDevice;
    } catch {
      return null;
    }
  }

  async save(device: DesktopDevice): Promise<void> {
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(device, null, 2), "utf-8");
  }
}

export async function ensureDeviceIdentity(
  store: DeviceIdentityStore,
  deviceLabel: string
): Promise<DesktopDevice> {
  const existing = await store.load();
  if (existing) {
    const touched: DesktopDevice = { ...existing, lastSeen: new Date().toISOString() };
    await store.save(touched);
    return touched;
  }

  const device: DesktopDevice = {
    deviceId: randomUUID(),
    deviceLabel,
    lastSeen: new Date().toISOString(),
  };
  await store.save(device);
  return device;
}
