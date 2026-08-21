import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { DriveFolderPicker } from "./DriveFolderPicker.js";
import type { SourcesApi } from "./api/sourcesClient.js";

function api(overrides: Partial<SourcesApi> = {}): SourcesApi {
  return {
    listMounts: vi.fn(async () => []),
    listGithubRepositories: vi.fn(async () => []),
    createGithubMount: vi.fn(async () => ({ mountId: "m" })),
    createDrivePickerSession: vi.fn(async () => ({
      accessToken: "short-lived-token",
      apiKey: "browser-key",
      appId: "913961882221",
    })),
    createDriveMount: vi.fn(async () => ({ mountId: "mount-d1" })),
    listTrackedFiles: vi.fn(async () => ({
      mountId: "m",
      sourceType: "GOOGLE_DRIVE",
      descriptor: null,
      files: [],
    })),
    retryFailedAnalyses: vi.fn(async () => ({ requeued: 0, expired: 0 })),
    ...overrides,
  };
}

afterEach(() => cleanup());

test("고른 파일로 Mount 를 만들고 목록 갱신을 알린다", async () => {
  const client = api();
  const onMounted = vi.fn();
  // 실제 Google Picker 는 외부 스크립트라 여기서 열 수 없다. 선택 결과만
  // 대체한다 — 이 컴포넌트의 책임은 세션 발급과 Mount 생성 사이의 배선이다.
  const pickFiles = vi.fn(async () => ["file-a", "folder-b"]);

  render(
    <DriveFolderPicker
      api={client}
      connectionId="conn-d1"
      riskWorkspaceId="vws-1"
      onMounted={onMounted}
      pickFiles={pickFiles}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Google Drive 에서 선택" }),
  );

  await waitFor(() => expect(onMounted).toHaveBeenCalledOnce());
  expect(pickFiles).toHaveBeenCalledWith({
    accessToken: "short-lived-token",
    apiKey: "browser-key",
    appId: "913961882221",
  });
  expect(client.createDriveMount).toHaveBeenCalledWith({
    connectionId: "conn-d1",
    riskWorkspaceId: "vws-1",
    selectedFileIds: ["file-a", "folder-b"],
  });
});

test("사용자가 Picker 를 닫으면 아무 일도 하지 않는다", async () => {
  const client = api();
  const onMounted = vi.fn();

  render(
    <DriveFolderPicker
      api={client}
      connectionId="conn-d1"
      riskWorkspaceId="vws-1"
      onMounted={onMounted}
      pickFiles={vi.fn(async () => null)}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Google Drive 에서 선택" }),
  );

  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Google Drive 에서 선택" }),
    ).toBeTruthy(),
  );
  expect(client.createDriveMount).not.toHaveBeenCalled();
  expect(onMounted).not.toHaveBeenCalled();
  // 닫은 것은 오류가 아니다. 빨간 문구가 뜨면 사용자가 실패로 오해한다.
  expect(screen.queryByText(/못했습니다|만료|설정되지/)).toBeNull();
});

test("API 키가 없는 배포에서는 관리자 설정 문제라고 말한다", async () => {
  // "다시 시도해 주세요"는 거짓 안내다. 사용자가 고칠 수 있는 문제가 아니다.
  const client = api({
    createDrivePickerSession: vi.fn(async () => ({
      accessToken: "tok",
      apiKey: null,
      appId: null,
    })),
  });

  render(
    <DriveFolderPicker
      api={client}
      connectionId="conn-d1"
      riskWorkspaceId="vws-1"
      onMounted={vi.fn()}
      pickFiles={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Google Drive 에서 선택" }),
  );

  expect(await screen.findByText(/GOOGLE_PICKER_API_KEY/)).toBeTruthy();
});

test("토큰이 만료되면 다시 연결하라고 말한다", async () => {
  const client = api({
    createDrivePickerSession: vi.fn(async () => {
      throw new Error("request failed at /drive/picker-session: 401");
    }),
  });

  render(
    <DriveFolderPicker
      api={client}
      connectionId="conn-d1"
      riskWorkspaceId="vws-1"
      onMounted={vi.fn()}
      pickFiles={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Google Drive 에서 선택" }),
  );

  expect(await screen.findByText(/다시 시작해 주세요/)).toBeTruthy();
});
