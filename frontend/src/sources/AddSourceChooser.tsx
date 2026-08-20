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

import { Button } from "../shared/ui/index.js";
import type { SourceApiClient } from "./api/connectionClient.js";

export type SourceProviderType = "GOOGLE_DRIVE" | "GITHUB" | "LOCAL";

export interface AddSourceChooserProps {
  onSelect: (type: SourceProviderType) => void;
  isDesktop: boolean;
  riskWorkspaceId: string;
  connectionApiClient: SourceApiClient;
  navigateExternal?: (url: string) => void;
}

export function AddSourceChooser({
  onSelect,
  isDesktop,
  riskWorkspaceId,
  connectionApiClient,
  navigateExternal = (url) => window.location.assign(url),
}: AddSourceChooserProps) {
  const [error, setError] = useState<string | null>(null);

  const handleDriveClick = async (): Promise<void> => {
    onSelect("GOOGLE_DRIVE");
    setError(null);
    try {
      const { authorizeUrl } = await connectionApiClient.startDriveConnection(riskWorkspaceId);
      navigateExternal(authorizeUrl);
    } catch {
      setError("Google Drive 연결을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  const handleGithubClick = async (): Promise<void> => {
    onSelect("GITHUB");
    setError(null);
    try {
      const { authorizeUrl } = await connectionApiClient.startGithubConnection(riskWorkspaceId);
      navigateExternal(authorizeUrl);
    } catch {
      setError("GitHub 연결을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  return (
    <div className="source-provider-grid">
      <h2>Add Source</h2>
      <Button type="button" variant="secondary" onClick={() => void handleDriveClick()}>
        Google Drive
      </Button>
      <Button type="button" variant="secondary" onClick={() => void handleGithubClick()}>
        GitHub Repository
      </Button>
      <Button type="button" variant="secondary" onClick={() => onSelect("LOCAL")} disabled={!isDesktop}>
        Local Folder{isDesktop ? "" : " (Desktop only)"}
      </Button>
      {error && <p className="source-error" role="alert">{error}</p>}
    </div>
  );
}
