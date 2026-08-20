/**
 * 개발 확인용 임시 진입점. frontend/src/app/**(Agent 1 소유)에 진짜
 * app shell/router가 생기면 이 파일은 필요 없어진다 — 지금은 우리
 * sources/** 컴포넌트를 브라우저에서 눈으로 확인하기 위한 용도로만 쓴다.
 */

import { createRoot } from "react-dom/client";

import { AddSourceChooser, type SourceProviderType } from "../AddSourceChooser.js";
import { ConnectLocalSource } from "../ConnectLocalSource.js";
import { detectPlatformAdapter } from "../platform/PlatformAdapter.js";

function DevPreview() {
  const platform = detectPlatformAdapter();

  const handleSelect = (type: SourceProviderType): void => {
    console.log("selected source type:", type);
  };

  return (
    <div style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>sources/ 개발용 미리보기</h1>
      <p>platform: {platform.platform}</p>
      <AddSourceChooser onSelect={handleSelect} isDesktop={platform.platform === "desktop"} />
      <hr />
      <ConnectLocalSource platform={platform} />
    </div>
  );
}

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(<DevPreview />);
}
