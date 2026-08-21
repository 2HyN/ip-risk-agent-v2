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
 *
 * 화면은 두 단계다. **연결**(OAuth/App 설치)이 끝나면 provider 가 브라우저를
 * 콜백으로 보내고, 백엔드가 `?connection=&provider=` 를 붙여 이 화면으로
 * 돌려보낸다. 그때부터가 **감시 대상 선택**이다. 연결만으로는 아무것도
 * 감시하지 않으므로 이 단계를 건너뛰면 사용자는 "연결했는데 아무 일도
 * 없다"는 상태에 놓인다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { HttpConnectionApiClient } from "./api/connectionClient.js";
import { HttpSourcesApi, type Mount } from "./api/sourcesClient.js";
import { AddSourceChooser, type SourceProviderType } from "./AddSourceChooser.js";
import { ConnectedSourceList } from "./ConnectedSourceList.js";
import { ConnectLocalSource } from "./ConnectLocalSource.js";
import { GithubRepositoryPicker } from "./GithubRepositoryPicker.js";
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
  const sourcesApi = useMemo(() => new HttpSourcesApi(apiBaseUrl), [apiBaseUrl]);
  const [selected, setSelected] = useState<SourceProviderType | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const [mounts, setMounts] = useState<Mount[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setListError(null);
    try {
      setMounts(await sourcesApi.listMounts(workspace.id));
    } catch (cause) {
      console.error(cause);
      setListError("연결된 Source 를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [sourcesApi, workspace.id]);

  useEffect(() => {
    setLoading(true);
    void refresh();
  }, [refresh]);

  // provider 콜백이 남긴 값. 이 연결로 무엇을 감시할지 이어서 고른다.
  const connectionId = searchParams.get("connection");
  const provider = searchParams.get("provider");

  const finishConnecting = useCallback(() => {
    // 선택이 끝나면 질의를 지운다. 남겨 두면 새로고침할 때마다 이미 끝난
    // 선택 화면이 다시 뜬다.
    const next = new URLSearchParams(searchParams);
    next.delete("connection");
    next.delete("provider");
    setSearchParams(next, { replace: true });
    void refresh();
  }, [refresh, searchParams, setSearchParams]);

  return (
    <div className="content">
      <header>
        <h1>Connected sources</h1>
        <p>
          이 Risk Workspace 에 연결할 Source 를 고릅니다. 연결은 이 워크스페이스
          범위로만 만들어집니다.
        </p>
      </header>

      <ConnectedSourceList mounts={mounts} loading={loading} error={listError} />

      {connectionId && provider === "github" ? (
        <GithubRepositoryPicker
          api={sourcesApi}
          connectionId={connectionId}
          riskWorkspaceId={workspace.id}
          onMounted={finishConnecting}
        />
      ) : (
        <>
          <AddSourceChooser
            onSelect={setSelected}
            isDesktop={platform.platform === "desktop"}
            riskWorkspaceId={workspace.id}
            connectionApiClient={connectionApiClient}
          />

          {selected === "LOCAL" && <ConnectLocalSource platform={platform} />}
        </>
      )}

      {connectionId && provider === "google_drive" && (
        // Drive 는 파일 선택에 Google Picker 가 필요하다. 아직 붙이지 않았다.
        // 연결은 만들어졌으므로 그 사실만은 정확히 알린다.
        <p>
          Google Drive 연결은 만들어졌지만, 폴더를 고르는 화면이 아직
          준비되지 않았습니다.
        </p>
      )}
    </div>
  );
}
