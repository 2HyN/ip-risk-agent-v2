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
  /**
   * 이미 살아 있는 GitHub 연결이 있으면 그것을 쓴다.
   *
   * 저장소를 더 붙이려는 사람이 가장 먼저 누르는 것은 "Add Source" 다. 그런데
   * 거기서 설치 화면으로 보내면 GitHub 은 **저장소 선택이 바뀔 때만** 돌려보내
   * 므로, 새로 고를 것이 없는 사람은 돌아오지 못한다. 이미 붙어 있는 연결이
   * 있으면 나갈 이유가 없다 — 저장소 목록은 앱에서 바로 볼 수 있다.
   */
  onUseExistingGithub?: (() => void) | null;
}

export function AddSourceChooser({
  onSelect,
  isDesktop,
  riskWorkspaceId,
  connectionApiClient,
  navigateExternal = (url) => window.location.assign(url),
  onUseExistingGithub = null,
}: AddSourceChooserProps) {
  const [error, setError] = useState<string | null>(null);

  /**
   * D1 — Drive 는 밖으로 나갔다 오지 않는다.
   *
   * 승인 화면도 Picker 도 없다. 사용자가 폴더를 서비스 계정에 공유하는 것이
   * 승인이므로, 여기서는 그 안내를 여는 것으로 끝난다.
   */
  const handleDriveClick = (): void => {
    onSelect("GOOGLE_DRIVE");
    setError(null);
  };

  /** GitHub 설치 화면으로 보낸다. 저장소를 설치에 **추가**하려면 이 길뿐이다. */
  const startGithubInstall = async (): Promise<void> => {
    onSelect("GITHUB");
    setError(null);
    try {
      const { authorizeUrl } = await connectionApiClient.startGithubConnection(riskWorkspaceId);
      navigateExternal(authorizeUrl);
    } catch {
      setError("GitHub 연결을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    }
  };

  const handleGithubClick = async (): Promise<void> => {
    if (onUseExistingGithub !== null) {
      onSelect("GITHUB");
      setError(null);
      onUseExistingGithub();
      return;
    }
    await startGithubInstall();
  };

  return (
    <div className="source-provider-grid">
      <h2>Add Source</h2>
      <Button type="button" variant="secondary" onClick={handleDriveClick}>
        Google Drive
      </Button>
      <Button type="button" variant="secondary" onClick={() => void handleGithubClick()}>
        GitHub Repository
      </Button>
      {onUseExistingGithub === null ? null : (
        <>
          <p className="source-hint">
            이미 연결된 GitHub 설치가 있습니다. 접근 가능한 저장소는 위에서 바로
            고를 수 있습니다.
          </p>
          {/*
            설치에 없는 저장소를 붙이려면 GitHub 으로 가야 한다. App 이 스스로
            저장소 접근 권한을 얻는 API 는 없기 때문이다.

            이 길을 없애면 **설치에 없는 저장소는 영영 붙일 수 없다.** 실제로
            그렇게 만들어 버린 적이 있다 — 기존 연결을 쓰게 하면서 GitHub 으로
            나가는 유일한 버튼을 대체해 버렸다.
          */}
          <Button type="button" variant="secondary" onClick={() => void startGithubInstall()}>
            GitHub 에서 저장소 추가
          </Button>
        </>
      )}
      <Button type="button" variant="secondary" onClick={() => onSelect("LOCAL")} disabled={!isDesktop}>
        Local Folder{isDesktop ? "" : " (Desktop only)"}
      </Button>
      {error && <p className="source-error" role="alert">{error}</p>}
    </div>
  );
}
