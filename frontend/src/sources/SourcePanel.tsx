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
 * 돌려보낸다. 그때부터가 **감시 대상 선택**이다.
 *
 * 선택 단계는 URL 질의에만 두면 안 된다. 사용자가 GitHub 설정 페이지를
 * 다녀오거나, 새로고침하거나, 앱 안에서 다른 화면을 들렀다 오면 질의가
 * 사라진다. 연결은 서버에 멀쩡히 살아 있는데 화면만 그것을 잊어버려,
 * "연결했는데 고를 방법이 없는" 상태에 갇힌다. 그래서 진행 중인 선택을
 * sessionStorage 에 남겨 두고, Mount 를 만들거나 사용자가 취소할 때 지운다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { HttpConnectionApiClient } from "./api/connectionClient.js";
import { HttpSourcesApi, type Mount } from "./api/sourcesClient.js";
import { AddSourceChooser, type SourceProviderType } from "./AddSourceChooser.js";
import { ConnectedSourceList } from "./ConnectedSourceList.js";
import { ConnectLocalSource } from "./ConnectLocalSource.js";
import { DriveFolderPicker } from "./DriveFolderPicker.js";
import { GithubRepositoryPicker } from "./GithubRepositoryPicker.js";
import { detectPlatformAdapter } from "./platform/PlatformAdapter.js";
import { useSession } from "../auth/session";
import { useWorkspace } from "../workspace/workspace-context";

export type SourcePanelProps = {
  /** 비우면 same-origin 으로 호출한다. Vite dev server 가 /api 를 프록시한다. */
  apiBaseUrl?: string;
};

type PendingConnection = {
  connectionId: string;
  provider: string;
};

/** 워크스페이스마다 따로 둔다. 다른 VWS 의 선택 단계가 새어 오면 안 된다. */
function pendingKey(workspaceId: string): string {
  return `iprisk:pending-connection:${workspaceId}`;
}

function readPending(workspaceId: string): PendingConnection | null {
  try {
    const raw = sessionStorage.getItem(pendingKey(workspaceId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as PendingConnection).connectionId === "string" &&
      typeof (parsed as PendingConnection).provider === "string"
    ) {
      return parsed as PendingConnection;
    }
  } catch {
    // storage 접근이 막힌 환경(사생활 보호 모드 일부)에서는 질의 기반으로만
    // 동작한다. 기능이 죽는 것보다 낫다.
  }
  return null;
}

function writePending(workspaceId: string, value: PendingConnection | null): void {
  try {
    if (value === null) {
      sessionStorage.removeItem(pendingKey(workspaceId));
    } else {
      sessionStorage.setItem(pendingKey(workspaceId), JSON.stringify(value));
    }
  } catch {
    // 위와 같은 이유로 조용히 넘어간다.
  }
}

export function SourcePanel({ apiBaseUrl = "" }: SourcePanelProps) {
  const { workspace } = useWorkspace();
  // 제거는 Control 라우트라 CSRF 토큰이 필요하다. 세션의 클라이언트가
  // 그 토큰을 들고 있으므로 이 경로만 세션 API 를 쓴다.
  const { api: controlApi } = useSession();
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
  const [pending, setPending] = useState<PendingConnection | null>(() =>
    readPending(workspace.id),
  );
  const [removeError, setRemoveError] = useState<string | null>(null);

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

  // 워크스페이스를 오가면 그 워크스페이스의 진행 상태를 다시 읽는다.
  useEffect(() => {
    setPending(readPending(workspace.id));
  }, [workspace.id]);

  // 콜백이 남긴 질의를 durable 한 진행 상태로 승격시킨다. 질의는 새로고침과
  // 화면 이동에서 살아남지 못하므로 URL 은 진실의 원본이 될 수 없다.
  useEffect(() => {
    const connectionId = searchParams.get("connection");
    const provider = searchParams.get("provider");
    if (!connectionId || !provider) return;

    const next = { connectionId, provider };
    writePending(workspace.id, next);
    setPending(next);

    // 저장했으니 URL 은 정리한다. 남겨 두면 이 주소를 북마크하거나 공유했을
    // 때 이미 끝난 선택 화면이 다시 뜬다.
    const cleaned = new URLSearchParams(searchParams);
    cleaned.delete("connection");
    cleaned.delete("provider");
    setSearchParams(cleaned, { replace: true });
  }, [searchParams, setSearchParams, workspace.id]);

  const clearPending = useCallback(() => {
    writePending(workspace.id, null);
    setPending(null);
  }, [workspace.id]);

  const finishConnecting = useCallback(() => {
    clearPending();
    void refresh();
  }, [clearPending, refresh]);

  const removeMount = useCallback(
    async (mount: Mount) => {
      // 원본은 건드리지 않는다 — 감시만 중단된다. 그래도 목록에서 사라지는
      // 조작이므로 한 번 확인한다.
      if (
        !window.confirm(
          `"${mount.alias}" 감시를 중단할까요?
원본 저장소/파일은 삭제되지 않습니다.`,
        )
      ) {
        return;
      }
      setRemoveError(null);
      try {
        await controlApi.removeMount(workspace.id, mount.id);
        await refresh();
      } catch (cause) {
        console.error(cause);
        setRemoveError(
          "감시를 중단하지 못했습니다. 이 워크스페이스의 OWNER 인지 확인해 주세요.",
        );
      }
    },
    [controlApi, refresh, workspace.id],
  );

  return (
    <div className="content">
      <header>
        <h1>Connected sources</h1>
        <p>
          이 Risk Workspace 에 연결할 Source 를 고릅니다. 연결은 이 워크스페이스
          범위로만 만들어집니다.
        </p>
      </header>

      <ConnectedSourceList
        mounts={mounts}
        loading={loading}
        error={listError}
        onRemove={removeMount}
      />
      {removeError && <p style={{ color: "red" }}>{removeError}</p>}

      {pending?.provider === "github" ? (
        <>
          <GithubRepositoryPicker
            api={sourcesApi}
            connectionId={pending.connectionId}
            riskWorkspaceId={workspace.id}
            onMounted={finishConnecting}
          />
          <p>
            <button type="button" onClick={clearPending}>
              저장소 선택 그만두기
            </button>
          </p>
        </>
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

      {pending?.provider === "google_drive" && (
        <>
          <DriveFolderPicker
            api={sourcesApi}
            connectionId={pending.connectionId}
            riskWorkspaceId={workspace.id}
            onMounted={finishConnecting}
          />
          <p>
            <button type="button" onClick={clearPending}>
              폴더 선택 그만두기
            </button>
          </p>
        </>
      )}
    </div>
  );
}
