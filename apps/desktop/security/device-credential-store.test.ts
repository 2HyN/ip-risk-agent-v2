import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  EncryptedFileDeviceCredentialStore,
  type SafeEncryption,
} from "./device-credential-store.js";

const credential = "desktop-device-credential-at-least-32-characters";

class FakeSafeEncryption implements SafeEncryption {
  available = true;
  isEncryptionAvailable(): boolean { return this.available; }
  encryptString(value: string): Uint8Array { return Buffer.from(`encrypted:${value.split("").reverse().join("")}`); }
  decryptString(value: Uint8Array): string { return Buffer.from(value).toString("utf8").replace("encrypted:", "").split("").reverse().join(""); }
}

test("device credential is encrypted at rest and survives restart", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-credential-"));
  try {
    const file = join(dir, "credential.json");
    const encryption = new FakeSafeEncryption();
    await new EncryptedFileDeviceCredentialStore(file, encryption).saveCredential(credential);

    assert.equal(readFileSync(file, "utf8").includes(credential), false);
    assert.equal(
      await new EncryptedFileDeviceCredentialStore(file, encryption).getCredential(),
      credential,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("credential storage fails closed when OS encryption is unavailable", async () => {
  const dir = mkdtempSync(join(tmpdir(), "iprisk-credential-"));
  try {
    const encryption = new FakeSafeEncryption();
    encryption.available = false;
    const store = new EncryptedFileDeviceCredentialStore(join(dir, "credential.json"), encryption);
    await assert.rejects(() => store.saveCredential(credential), /safeStorage/);
    assert.equal(await store.getCredential(), null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
