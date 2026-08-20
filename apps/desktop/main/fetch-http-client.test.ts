import assert from "node:assert/strict";
import test from "node:test";

import { FetchHttpClient } from "./desktop-event-reporter.js";

test("authenticated Desktop requests use bearer identity and retry only transient failures", async () => {
  const calls: RequestInit[] = [];
  const client = new FetchHttpClient(
    "https://api.example.com",
    { getCredential: async () => "desktop-device-credential-at-least-32-characters" },
    async (_input, init) => {
      calls.push(init ?? {});
      if (calls.length === 1) return new Response("", { status: 503 });
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
    async () => undefined,
  );

  assert.deepEqual(await client.postJson("/desktop/events", { event_id: "event-1" }), { status: "ok" });
  assert.equal(calls.length, 2);
  assert.equal(
    new Headers(calls[0]?.headers).get("Authorization"),
    "Bearer desktop-device-credential-at-least-32-characters",
  );
});

test("Desktop requests fail before fetch when enrollment is missing", async () => {
  let called = false;
  const client = new FetchHttpClient(
    "https://api.example.com",
    { getCredential: async () => null },
    async () => { called = true; return new Response("{}"); },
  );
  await assert.rejects(() => client.postJson("/desktop/events", {}), /enrollment/);
  assert.equal(called, false);
});
