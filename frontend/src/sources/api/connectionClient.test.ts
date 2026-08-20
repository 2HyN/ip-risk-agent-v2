// @vitest-environment node

import { test } from "vitest";
import assert from "node:assert/strict";

import { HttpConnectionApiClient, type FetchLike } from "./connectionClient.js";

function fakeFetch(
  responses: Record<string, { status: number; body: unknown }>
): { fetchImpl: FetchLike; calls: Array<{ url: string; body: unknown }> } {
  const calls: Array<{ url: string; body: unknown }> = [];
  const fetchImpl = (async (input: string | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ url, body });
    const path = Object.keys(responses).find((p) => url.endsWith(p));
    const match = path ? responses[path] : undefined;
    if (!match) {
      throw new Error(`no fake response registered for ${url}`);
    }
    return {
      ok: match.status < 400,
      status: match.status,
      json: async () => match.body,
    } as Response;
  }) as FetchLike;
  return { fetchImpl, calls };
}

test("startDriveConnection posts risk_workspace_id and returns authorizeUrl/state", async () => {
  const { fetchImpl, calls } = fakeFetch({
    "/api/v1/source-connections/google-drive/start": {
      status: 200,
      body: { authorize_url: "https://accounts.google.com/o/oauth2/v2/auth?...", state: "abc123" },
    },
  });
  const client = new HttpConnectionApiClient("http://localhost:8000", fetchImpl);

  const result = await client.startDriveConnection("rw1");

  assert.equal(result.authorizeUrl, "https://accounts.google.com/o/oauth2/v2/auth?...");
  assert.equal(result.state, "abc123");
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.url, "http://localhost:8000/api/v1/source-connections/google-drive/start");
  assert.deepEqual(calls[0]?.body, { risk_workspace_id: "rw1" });
});

test("startGithubConnection posts risk_workspace_id and returns authorizeUrl/state", async () => {
  const { fetchImpl, calls } = fakeFetch({
    "/api/v1/source-connections/github/install/start": {
      status: 200,
      body: { authorize_url: "https://github.com/apps/ip-risk-agent/installations/new?state=xyz", state: "xyz" },
    },
  });
  const client = new HttpConnectionApiClient("http://localhost:8000", fetchImpl);

  const result = await client.startGithubConnection("rw1");

  assert.equal(result.state, "xyz");
  assert.ok(result.authorizeUrl.includes("installations/new"));
  assert.equal(calls[0]?.body && (calls[0].body as { risk_workspace_id: string }).risk_workspace_id, "rw1");
});

test("throws when the server responds with an error status", async () => {
  const { fetchImpl } = fakeFetch({
    "/api/v1/source-connections/google-drive/start": { status: 500, body: {} },
  });
  const client = new HttpConnectionApiClient("http://localhost:8000", fetchImpl);

  await assert.rejects(() => client.startDriveConnection("rw1"));
});
