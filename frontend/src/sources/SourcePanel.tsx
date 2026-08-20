/**
 * Control Plane 의 `sourcePanel` 슬롯에 들어가는 Source Plane 화면.
 *
 * Agent 1 은 `frontend/src/sources/**` 를 직접 import 하지 않고, Agent 2 는
 * Control 의 라우팅을 모른다. 그 사이를 Integration 이 이 컴포넌트로 잇는다
 * (docs/INTEGRATION.md 5절).
 *
 * 여기서 `riskWorkspaceId` 를 현재 VWS 컨텍스트에서 읽는다. Agent 2 가
 * 개발용으로 쓰던 `"dev-workspace"` 하드코딩은 이 경로가 생기면서 사라진다
 * (docs/INTEGRATION.md 5절).
 */

import { useMemo, useState } from "react";

import { HttpConnectionApiClient } from "./api/connectionClient.js";
import { AddSourceChooser, type SourceProviderType } from "./AddSourceChooser.js";
import { ConnectLocalSource } from "./ConnectLocalSource.js";
import { detectPlatformAdapter } from "./platform/PlatformAdapter.js";
import { useWorkspace } from "../workspace/workspace-context";

export type SourcePanelProps = {
  /** 비우면 same-origin 으로 호출한다. Vite dev server 가 /api 를 프록시한다. */
  apiBaseUrl?: string;
};

export function SourcePanel({ apiBaseUrl = "" }: SourcePanelProps) {
  const { workspace } = useWorkspace();
  const platform = useMemo(() => detectPlatformAdapter(), []);
  const connectionApiClient = useMemo(
    () => new HttpConnectionApiClient(apiBaseUrl),
    [apiBaseUrl],
  );
  const [selected, setSelected] = useState<SourceProviderType | null>(null);

  return (
    <div className="content">
      <header>
        <h1>Connected sources</h1>
        <p>
          이 Risk Workspace 에 연결할 Source 를 고릅니다. 연결은 이 워크스페이스
          범위로만 만들어집니다.
        </p>
      </header>

      <AddSourceChooser
        onSelect={setSelected}
        isDesktop={platform.platform === "desktop"}
        riskWorkspaceId={workspace.id}
        connectionApiClient={connectionApiClient}
      />

      {selected === "LOCAL" && <ConnectLocalSource platform={platform} />}
    </div>
  );
}
