import { expect, test } from "vitest";

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

  expect(result.authorizeUrl).toBe("https://accounts.google.com/o/oauth2/v2/auth?...");
  expect(result.state).toBe("abc123");
  expect(calls).toHaveLength(1);
  expect(calls[0]?.url).toBe("http://localhost:8000/api/v1/source-connections/google-drive/start");
  expect(calls[0]?.body).toEqual({ risk_workspace_id: "rw1" });
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

  expect(result.state).toBe("xyz");
  expect(result.authorizeUrl).toContain("installations/new");
  expect(calls[0]?.body && (calls[0].body as { risk_workspace_id: string }).risk_workspace_id).toBe("rw1");
});

test("throws when the server responds with an error status", async () => {
  const { fetchImpl } = fakeFetch({
    "/api/v1/source-connections/google-drive/start": { status: 500, body: {} },
  });
  const client = new HttpConnectionApiClient("http://localhost:8000", fetchImpl);

  await expect(client.startDriveConnection("rw1")).rejects.toThrow();
});
