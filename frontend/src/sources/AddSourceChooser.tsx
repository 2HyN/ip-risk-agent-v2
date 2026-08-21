/**
 * Agent 2 Spec §39 "Add Source chooser". 지금은 기능 위주 — 스타일은
 * 다음 단계에서.
 *
 * Google Drive/GitHub 버튼은 이제 실제로 백엔드의 연결 시작 라우터를
 * 호출하고, 받은 authorize_url로 브라우저를 이동시킨다 (실제 OAuth/App
 * 설치 흐름 시작). riskWorkspaceId는 "지금 어느 VWS에 연결하는지"를
 * 나타내는데, 실제 VWS 선택 UI는 Agent 1의 app shell 영역이라 지금은
 * 호출하는 쪽에서 값을 그대로 넘겨받는 형태로만 되어 있다.
 */

import { useState } from "react";

import type { ConnectionApiClient } from "./api/connectionClient.js";

export type SourceProviderType = "GOOGLE_DRIVE" | "GITHUB" | "LOCAL";

export interface AddSourceChooserProps {
  onSelect: (type: SourceProviderType) => void;
  isDesktop: boolean;
  riskWorkspaceId: string;
  connectionApiClient: ConnectionApiClient;
}

export function AddSourceChooser({
  onSelect,
  isDesktop,
  riskWorkspaceId,
  connectionApiClient,
}: AddSourceChooserProps) {
  const [error, setError] = useState<string | null>(null);

  const handleDriveClick = async (): Promise<void> => {
    onSelect("GOOGLE_DRIVE");
    setError(null);
    try {
      const { authorizeUrl } = await connectionApiClient.startDriveConnection(riskWorkspaceId);
      window.location.href = authorizeUrl;
    } catch (cause) {
      // 원인을 삼키면 "잠시 후 다시" 라는 안내가 영원히 맞지 않는 상황에서도
      // 사용자가 그대로 기다리게 된다. 상태 코드는 드러낸다.
      // 상태 코드가 없는 실패(요청이 나가지도 못한 경우)는 화면 문구만으로
      // 구분되지 않는다. 원인은 콘솔에 그대로 남긴다.
      console.error(cause);
      const reason = cause instanceof Error ? cause.message : "";
      setError(
        reason.includes("401")
          ? "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요."
          : reason.includes("403")
            ? "이 워크스페이스에 Source 를 연결할 권한이 없습니다."
            : "Google Drive 연결을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요."
      );
    }
  };

  const handleGithubClick = async (): Promise<void> => {
    onSelect("GITHUB");
    setError(null);
    try {
      const { authorizeUrl } = await connectionApiClient.startGithubConnection(riskWorkspaceId);
      window.location.href = authorizeUrl;
    } catch (cause) {
      // 원인을 삼키면 "잠시 후 다시" 라는 안내가 영원히 맞지 않는 상황에서도
      // 사용자가 그대로 기다리게 된다. 상태 코드는 드러낸다.
      // 상태 코드가 없는 실패(요청이 나가지도 못한 경우)는 화면 문구만으로
      // 구분되지 않는다. 원인은 콘솔에 그대로 남긴다.
      console.error(cause);
      const reason = cause instanceof Error ? cause.message : "";
      setError(
        reason.includes("401")
          ? "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요."
          : reason.includes("403")
            ? "이 워크스페이스에 Source 를 연결할 권한이 없습니다."
            : "GitHub 연결을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요."
      );
    }
  };

  return (
    <div>
      <h2>Add Source</h2>
      <button type="button" onClick={() => void handleDriveClick()}>
        Google Drive
      </button>
      <button type="button" onClick={() => void handleGithubClick()}>
        GitHub Repository
      </button>
      <button type="button" onClick={() => onSelect("LOCAL")} disabled={!isDesktop}>
        Local Folder{isDesktop ? "" : " (Desktop only)"}
      </button>
      {error && <p style={{ color: "red" }}>{error}</p>}
    </div>
  );
}
