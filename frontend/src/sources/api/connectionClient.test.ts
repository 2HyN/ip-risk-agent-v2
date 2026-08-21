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

test("연결 시작 요청은 세션 쿠키를 함께 보낸다", async () => {
  // 이 라우트는 Control 의 VWS Role 검사를 거친다. credentials 를 빼면 401 이
  // 나는데 화면에는 "연결 실패"로만 보여 원인을 찾기 어렵다.
  const captured: RequestInit[] = [];
  const fetchImpl = (async (_input: string | URL, init?: RequestInit) => {
    captured.push(init ?? {});
    return {
      ok: true,
      status: 200,
      json: async () => ({ authorize_url: "https://example.invalid", state: "s" }),
    } as Response;
  }) as FetchLike;

  const client = new HttpConnectionApiClient("", fetchImpl);
  await client.startGithubConnection("rw1");
  await client.startDriveConnection("rw1");

  assert.equal(captured.length, 2);
  for (const init of captured) {
    assert.equal(init.credentials, "include");
  }
});

test("기본 fetchImpl 은 전역 fetch 를 올바른 수신자로 부른다", async () => {
  // 전역 `fetch` 를 필드에 그대로 담으면 `this.fetchImpl(...)` 호출 시
  // 수신자가 클라이언트 인스턴스가 되어 브라우저가 TypeError 를 던진다.
  // 요청이 나가지 않으므로 서버 로그에도 네트워크 탭에도 흔적이 없고,
  // 화면에는 상태 코드 없는 일반 오류만 보여 원인을 찾기 어렵다.
  // 브라우저의 수신자 검사를 흉내 내 그 상태를 막는다.
  const calls: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = function (this: unknown, input: string | URL) {
    if (this !== undefined && this !== globalThis) {
      throw new TypeError(
        "'fetch' called on an object that does not implement interface Window."
      );
    }
    calls.push(String(input));
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({ authorize_url: "https://github.test/install", state: "s1" }),
    } as Response);
  } as unknown as typeof fetch;

  try {
    const client = new HttpConnectionApiClient("");
    const result = await client.startGithubConnection("rw1");
    assert.equal(result.authorizeUrl, "https://github.test/install");
    assert.deepEqual(calls, ["/api/v1/source-connections/github/install/start"]);
  } finally {
    globalThis.fetch = original;
  }
});
