/**
 * 선택 단계가 새로고침·화면 이동에서 살아남는지 잠근다.
 *
 * 콜백이 남기는 `?connection=&provider=` 질의는 새로고침 한 번에 사라진다.
 * 연결은 서버에 살아 있는데 화면만 잊어버리면, 사용자는 "연결했는데 고를
 * 방법이 없는" 상태에 갇힌다. 실제로 그 상태가 보고됐다.
 */

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

// SourcePanel 은 제거 경로에만 세션 API(CSRF 보유)를 쓴다. 테스트에서는
// 로그인 흐름 전체를 세우는 대신 그 API 만 대체한다.
const removeMountSpy = vi.fn(async () => undefined);
vi.mock("../auth/session", () => ({
  useSession: () => ({ api: { removeMount: removeMountSpy } }),
}));

import { SourcePanel } from "./SourcePanel.js";
import { WorkspaceProvider, type WorkspaceState } from "../workspace/workspace-context";

const WORKSPACE_ID = "workspace_test1";

function workspaceState(): WorkspaceState {
  return {
    workspace: { id: WORKSPACE_ID, name: "test" } as WorkspaceState["workspace"],
    membership: { role: "OWNER" } as WorkspaceState["membership"],
    role: "OWNER",
    canReview: true,
    canManageMembers: true,
    canManageSecurity: true,
    canViewAudit: true,
  };
}

/** 이 화면이 호출하는 API 전부를 fetch 수준에서 흉내 낸다. */
function stubFetch() {
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/mounts")) {
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/github/repositories")) {
      return new Response(
        JSON.stringify({
          repositories: [
            {
              id: 1,
              full_name: "Sora3780/ip-risk-agent",
              owner: "Sora3780",
              name: "ip-risk-agent",
              private: true,
              default_branch: "main",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchImpl);
  return fetchImpl;
}

function renderPanel(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <WorkspaceProvider value={workspaceState()}>
        <SourcePanel />
      </WorkspaceProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
  stubFetch();
  removeMountSpy.mockClear();
});

afterEach(() => {
  // 이 프로젝트의 vitest 설정에는 자동 cleanup 이 없다. 렌더가 다음
  // 테스트로 새면 같은 문구가 여러 개 잡혀 전부 오탐이 된다.
  cleanup();
});

test("콜백 질의가 있으면 저장소 선택 화면이 뜬다", async () => {
  renderPanel(`/sources?connection=conn-1&provider=github`);

  expect(await screen.findByText("감시할 저장소 선택")).toBeTruthy();
});

test("질의가 사라져도(새로고침) 선택 단계가 유지된다", async () => {
  // 1차 방문: 콜백 질의와 함께 도착 → 진행 상태가 저장된다.
  const first = renderPanel(`/sources?connection=conn-1&provider=github`);
  await screen.findByText("감시할 저장소 선택");
  first.unmount();

  // 2차 방문: 질의 없는 맨 주소. 새로고침이나 화면 이동 후가 이 모양이다.
  renderPanel(`/sources`);

  expect(await screen.findByText("감시할 저장소 선택")).toBeTruthy();
});

test("그만두기를 누르면 Add Source 선택으로 돌아간다", async () => {
  renderPanel(`/sources?connection=conn-1&provider=github`);
  await screen.findByText("감시할 저장소 선택");

  await userEvent.click(
    screen.getByRole("button", { name: "저장소 선택 그만두기" }),
  );

  expect(await screen.findByText("Add Source")).toBeTruthy();
  // 저장된 진행 상태도 지워져야 한다. 남으면 다음 방문에 다시 뜬다.
  expect(sessionStorage.getItem(`iprisk:pending-connection:${WORKSPACE_ID}`)).toBeNull();
});

test("다른 워크스페이스의 진행 상태는 새어 오지 않는다", async () => {
  sessionStorage.setItem(
    "iprisk:pending-connection:workspace_other",
    JSON.stringify({ connectionId: "conn-x", provider: "github" }),
  );

  renderPanel(`/sources`);

  expect(await screen.findByText("Add Source")).toBeTruthy();
  expect(screen.queryByText("감시할 저장소 선택")).toBeNull();
});


function stubFetchWithMounts() {
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/mounts")) {
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "mount-1",
              risk_workspace_id: WORKSPACE_ID,
              source_workspace_id: "sws-1",
              alias: "Drive (31 items)",
              mounted_by_user_id: "user-1",
              source_connection_id: "conn-1",
              status: "ACTIVE",
              created_at: "2026-08-21T06:06:40Z",
              updated_at: "2026-08-21T06:06:40Z",
            },
          ],
          next_cursor: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchImpl);
}

test("감시 중단은 확인을 거쳐 Control 제거 API 를 부른다", async () => {
  stubFetchWithMounts();
  vi.stubGlobal("confirm", vi.fn(() => true));

  renderPanel(`/sources`);
  await userEvent.click(await screen.findByRole("button", { name: "감시 중단" }));

  expect(removeMountSpy).toHaveBeenCalledWith(WORKSPACE_ID, "mount-1");
});

test("확인을 취소하면 아무것도 지우지 않는다", async () => {
  stubFetchWithMounts();
  vi.stubGlobal("confirm", vi.fn(() => false));

  renderPanel(`/sources`);
  await userEvent.click(await screen.findByRole("button", { name: "감시 중단" }));

  expect(removeMountSpy).not.toHaveBeenCalled();
});
