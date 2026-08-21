import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { GithubRepositoryPicker } from "./GithubRepositoryPicker.js";
import type { SourcesApi } from "./api/sourcesClient.js";

function api(overrides: Partial<SourcesApi> = {}): SourcesApi {
  return {
    listMounts: vi.fn(async () => []),
    listGithubRepositories: vi.fn(async () => [
      {
        id: 1,
        fullName: "Sora3780/ip-risk-agent",
        owner: "Sora3780",
        name: "ip-risk-agent",
        private: true,
        defaultBranch: "main",
      },
    ]),
    createGithubMount: vi.fn(async () => ({ mountId: "mount-1" })),
    ...overrides,
  };
}

test("설치된 저장소를 고르면 Mount 를 만들고 목록 갱신을 알린다", async () => {
  // App 설치만으로는 아무것도 감시하지 않는다. 이 단계가 빠지면 사용자는
  // "연결했는데 아무 일도 없다"는 상태에 놓인다.
  const client = api();
  const onMounted = vi.fn();

  render(
    <GithubRepositoryPicker
      api={client}
      connectionId="conn-1"
      riskWorkspaceId="vws-1"
      onMounted={onMounted}
    />
  );

  const button = await screen.findByRole("button", {
    name: /Sora3780\/ip-risk-agent/,
  });
  await userEvent.click(button);

  await waitFor(() => expect(onMounted).toHaveBeenCalledOnce());
  expect(client.createGithubMount).toHaveBeenCalledWith({
    connectionId: "conn-1",
    riskWorkspaceId: "vws-1",
    owner: "Sora3780",
    repo: "ip-risk-agent",
  });
});

test("연결을 찾을 수 없으면 다시 연결하라고 말한다", async () => {
  // "불러오지 못했습니다"로 뭉뚱그리면 사용자가 새로고침만 반복하게 된다.
  const client = api({
    listGithubRepositories: vi.fn(async () => {
      throw new Error("request failed at /github/repositories: 404");
    }),
  });

  render(
    <GithubRepositoryPicker
      api={client}
      connectionId="gone"
      riskWorkspaceId="vws-1"
      onMounted={vi.fn()}
    />
  );

  expect(await screen.findByText(/연결을 다시 시작/)).toBeTruthy();
});

test("설치에 포함된 저장소가 없으면 그 사실을 말한다", async () => {
  const client = api({ listGithubRepositories: vi.fn(async () => []) });

  render(
    <GithubRepositoryPicker
      api={client}
      connectionId="conn-1"
      riskWorkspaceId="vws-1"
      onMounted={vi.fn()}
    />
  );

  expect(await screen.findByText(/저장소가 없습니다/)).toBeTruthy();
});
