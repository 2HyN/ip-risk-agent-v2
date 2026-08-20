import { chmod, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

export interface SafeEncryption {
  isEncryptionAvailable(): boolean;
  encryptString(value: string): Uint8Array;
  decryptString(value: Uint8Array): string;
}

interface StoredCredential {
  version: 1;
  ciphertext: string;
}

export class EncryptedFileDeviceCredentialStore {
  constructor(
    private readonly filePath: string,
    private readonly encryption: SafeEncryption,
  ) {}

  async getCredential(): Promise<string | null> {
    try {
      if (!this.encryption.isEncryptionAvailable()) return null;
      const parsed = JSON.parse(await readFile(this.filePath, "utf8")) as StoredCredential;
      if (parsed.version !== 1 || typeof parsed.ciphertext !== "string") return null;
      const credential = this.encryption.decryptString(
        Buffer.from(parsed.ciphertext, "base64"),
      );
      return credential.length >= 32 ? credential : null;
    } catch {
      return null;
    }
  }

  async saveCredential(credential: string): Promise<void> {
    if (credential.length < 32) throw new Error("device credential is invalid");
    if (!this.encryption.isEncryptionAvailable()) {
      throw new Error("OS-backed safeStorage encryption is unavailable");
    }
    const encrypted = this.encryption.encryptString(credential);
    const payload: StoredCredential = {
      version: 1,
      ciphertext: Buffer.from(encrypted).toString("base64"),
    };
    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(payload), { encoding: "utf8", mode: 0o600 });
    await chmod(this.filePath, 0o600).catch(() => undefined);
  }

  async clear(): Promise<void> {
    await rm(this.filePath, { force: true });
  }
}
