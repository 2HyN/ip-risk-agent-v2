import { useState } from "react";

import type { PlatformAdapter } from "./platform/PlatformAdapter.js";

export interface ConnectLocalSourceProps {
  platform: PlatformAdapter;
}

export function ConnectLocalSource({ platform }: ConnectLocalSourceProps) {
  const [pickedPath, setPickedPath] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "picked" | "unavailable">("idle");

  const handlePick = async (): Promise<void> => {
    if (platform.platform !== "desktop") {
      setStatus("unavailable");
      return;
    }
    const result = await platform.chooseLocalDirectory();
    if (result) {
      setPickedPath(result.canonicalRootPath);
      setStatus("picked");
    }
  };

  return (
    <div>
      <h3>Local Folder</h3>
      <button type="button" onClick={() => void handlePick()} disabled={platform.platform !== "desktop"}>
        Choose Folder
      </button>
      {status === "unavailable" && <p>Local Folder는 Desktop 앱에서만 연결할 수 있습니다.</p>}
      {pickedPath && (
        <>
          <p>선택한 경로: {pickedPath}</p>
          <p style={{ color: "gray" }}>
            (서버가 mount ID를 발급해주는 다음 단계는 아직 배선 전입니다 — Integration 단계에서 연결 예정)
          </p>
        </>
      )}
    </div>
  );
}
