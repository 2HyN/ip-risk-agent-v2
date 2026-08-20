import assert from "node:assert/strict";
import test from "node:test";

import { DeviceEnrollmentClient } from "./device-enrollment-client.js";

test("enrollment exchanges the one-time challenge without an Authorization header", async () => {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const client = new DeviceEnrollmentClient(
    "https://api.example.com",
    async (input, init) => {
      calls.push({ url: String(input), init: init ?? {} });
      return new Response(JSON.stringify({
        device_credential: "returned-device-credential-at-least-32-characters",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    },
  );

  const result = await client.exchange(
    "one-time-challenge-at-least-32-characters",
    "device-1",
    "Developer PC",
  );

  assert.equal(result.deviceCredential.startsWith("returned-device"), true);
  assert.equal(new Headers(calls[0]?.init.headers).has("Authorization"), false);
  assert.deepEqual(JSON.parse(String(calls[0]?.init.body)), {
    challenge: "one-time-challenge-at-least-32-characters",
    device_id: "device-1",
    device_label: "Developer PC",
  });
});
