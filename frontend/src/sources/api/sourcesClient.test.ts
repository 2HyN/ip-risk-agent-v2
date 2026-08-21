// @vitest-environment node

import { test } from "vitest";
import assert from "node:assert/strict";

import { HttpSourcesApi, type FetchLike } from "./sourcesClient.js";

type Call = { url: string; method: string; body: unknown };

function fakeFetch(responses: Record<string, { status: number; body: unknown }>): {
  fetchImpl: FetchLike;
  calls: Call[];
} {
  const calls: Call[] = [];
  const fetchImpl = (async (input: string | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({
      url,
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    });
    const path = Object.keys(responses).find((p) => url.endsWith(p));
    const match = path ? responses[path] : undefined;
    if (!match) throw new Error(`no fake response registered for ${url}`);
    return {
      ok: match.status < 400,
      status: match.status,
      json: async () => match.body,
    } as Response;
  }) as FetchLike;
  return { fetchImpl, calls };
}

test("listMounts 는 Control 의 페이지 응답을 화면용 모양으로 바꾼다", async () => {
  const { fetchImpl, calls } = fakeFetch({
    "/api/v1/workspaces/vws-1/mounts": {
      status: 200,
      body: {
        items: [
          {
            id: "mount-1",
            risk_workspace_id: "vws-1",
            source_workspace_id: "sws-1",
            alias: "Sora3780/ip-risk-agent",
            mounted_by_user_id: "user-1",
            source_connection_id: "conn-1",
            status: "ACTIVE",
            created_at: "2026-08-21T00:00:00Z",
            updated_at: "2026-08-21T00:00:00Z",
          },
        ],
        next_cursor: null,
      },
    },
  });

  const mounts = await new HttpSourcesApi("", fetchImpl).listMounts("vws-1");

  assert.equal(calls[0]?.url, "/api/v1/workspaces/vws-1/mounts");
  assert.equal(mounts.length, 1);
  assert.equal(mounts[0]?.alias, "Sora3780/ip-risk-agent");
  assert.equal(mounts[0]?.sourceConnectionId, "conn-1");
});

test("workspace id 는 경로에 넣기 전에 인코딩한다", async () => {
  const { fetchImpl, calls } = fakeFetch({
    "/mounts": { status: 200, body: { items: [], next_cursor: null } },
  });

  await new HttpSourcesApi("", fetchImpl).listMounts("a/b");

  assert.equal(calls[0]?.url, "/api/v1/workspaces/a%2Fb/mounts");
});

test("createGithubMount 는 tracked_branch 를 보내지 않는다", async () => {
  // 서버가 저장소의 기본 브랜치를 조회해 채운다. 화면이 추측해 보내면
  // 실제 기본 브랜치와 어긋난 채로 감시가 걸린다.
  const { fetchImpl, calls } = fakeFetch({
    "/github/mounts": {
      status: 200,
      body: { server_mount_id: "mount-9", source_workspace_id: "sws-9" },
    },
  });

  const result = await new HttpSourcesApi("", fetchImpl).createGithubMount({
    connectionId: "conn-1",
    riskWorkspaceId: "vws-1",
    owner: "Sora3780",
    repo: "ip-risk-agent",
  });

  assert.equal(result.mountId, "mount-9");
  assert.equal(calls[0]?.method, "POST");
  assert.deepEqual(calls[0]?.body, {
    risk_workspace_id: "vws-1",
    owner: "Sora3780",
    repo: "ip-risk-agent",
  });
});

test("실패는 상태 코드를 담아 던진다", async () => {
  // 상태 코드를 잃으면 화면이 권한 문제와 없는 연결을 구분할 수 없다.
  const { fetchImpl } = fakeFetch({
    "/github/repositories": { status: 404, body: {} },
  });

  await assert.rejects(
    () => new HttpSourcesApi("", fetchImpl).listGithubRepositories("conn-x"),
    /404/
  );
});

test("기본 fetchImpl 은 전역 fetch 를 올바른 수신자로 부른다", async () => {
  // 전역 fetch 를 필드에 그대로 담으면 메서드 호출 시 수신자가 어긋나
  // TypeError 가 나고, 요청이 아예 나가지 않는다.
  const original = globalThis.fetch;
  const calls: string[] = [];
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
      json: async () => ({ items: [], next_cursor: null }),
    } as Response);
  } as unknown as typeof fetch;

  try {
    await new HttpSourcesApi("").listMounts("vws-1");
    assert.deepEqual(calls, ["/api/v1/workspaces/vws-1/mounts"]);
  } finally {
    globalThis.fetch = original;
  }
});
