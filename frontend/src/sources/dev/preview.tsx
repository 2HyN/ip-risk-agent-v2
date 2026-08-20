/**
 * 개발 확인용 임시 진입점. frontend/src/app/**(Agent 1 소유)에 진짜
 * app shell/router가 생기면 이 파일은 필요 없어진다 — 지금은 우리
 * sources/** 컴포넌트를 브라우저에서 눈으로 확인하기 위한 용도로만 쓴다.
 *
 * riskWorkspaceId는 실제 VWS 선택 UI가 없어서 개발용 placeholder를 쓴다
 * (진짜 VWS 목록/선택은 Agent 1의 app shell 영역).
 */

import { createRoot } from "react-dom/client";

import { HttpConnectionApiClient } from "../api/connectionClient.js";
import { AddSourceChooser, type SourceProviderType } from "../AddSourceChooser.js";
import { ConnectLocalSource } from "../ConnectLocalSource.js";
import { detectPlatformAdapter } from "../platform/PlatformAdapter.js";

const DEV_SERVER_BASE_URL = "http://localhost:8000";
const DEV_RISK_WORKSPACE_ID = "dev-workspace";

function DevPreview() {
  const platform = detectPlatformAdapter();
  const connectionApiClient = new HttpConnectionApiClient(DEV_SERVER_BASE_URL);

  const handleSelect = (type: SourceProviderType): void => {
    console.log("selected source type:", type);
  };

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>sources/ 개발용 미리보기</h1>
      <p>platform: {platform.platform}</p>
      <AddSourceChooser
        onSelect={handleSelect}
        isDesktop={platform.platform === "desktop"}
        riskWorkspaceId={DEV_RISK_WORKSPACE_ID}
        connectionApiClient={connectionApiClient}
      />
      <hr />
      <ConnectLocalSource platform={platform} />
    </div>
  );
}

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(<DevPreview />);
}
