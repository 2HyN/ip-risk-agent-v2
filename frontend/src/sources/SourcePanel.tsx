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
import {
  HttpSourcesApi,
  type AnalysisProgress,
  type Mount,
} from "./api/sourcesClient.js";
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
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [retryBusy, setRetryBusy] = useState(false);
  const [driveConnectionId, setDriveConnectionId] = useState<string | null>(null);
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);

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

  // 살아 있는 Drive 연결이 있으면 OAuth 를 다시 타지 않고 폴더 선택으로
  // 바로 간다. 매번 구글 동의 화면을 오가는 이중 수고를 없앤다.
  useEffect(() => {
    let cancelled = false;
    sourcesApi
      .listSourceConnections(workspace.id)
      .then((connections) => {
        if (cancelled) return;
        const drive = connections.find((c) => c.sourceType === "GOOGLE_DRIVE");
        setDriveConnectionId(drive ? drive.connectionId : null);
      })
      .catch((cause) => console.error(cause));
    return () => {
      cancelled = true;
    };
  }, [sourcesApi, workspace.id]);

  // 분석 진행 현황. 검토가 남아 있는 동안엔 5초마다 갱신한다 — 특허 한
  // 건이 수십 초라, 침묵은 "고장"으로 읽힌다.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const next = await sourcesApi.getAnalysisProgress(workspace.id);
        if (cancelled) return;
        setProgress(next);
        if (next.pending + next.processing > 0) {
          timer = setTimeout(() => void poll(), 5_000);
        }
      } catch (cause) {
        console.error(cause);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sourcesApi, workspace.id, retryMessage]);

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

  const retryFailed = useCallback(async () => {
    // 큐 재시도가 소진돼 폐기된 분석을 되살린다. 성공분은 건너뛰고 실패분만
    // 재큐잉되므로 여러 번 눌러도 안전하다.
    setRetryMessage(null);
    setRetryBusy(true);
    try {
      const result = await sourcesApi.retryFailedAnalyses(workspace.id);
      setRetryMessage(
        result.requeued === 0 && result.expired === 0
          ? "다시 실행할 실패 분석이 없습니다."
          : `분석 ${result.requeued}건을 다시 시작했습니다.` +
              (result.expired > 0
                ? ` ${result.expired}건은 보존 기간(7일)이 지나 폴더를 다시 선택해야 합니다.`
                : ""),
      );
    } catch (cause) {
      console.error(cause);
      setRetryMessage("실패한 분석을 다시 시작하지 못했습니다.");
    } finally {
      setRetryBusy(false);
    }
  }, [sourcesApi, workspace.id]);

  const renameMount = useCallback(
    async (mount: Mount) => {
      // 표시 이름만 바꾼다. 실제 폴더/저장소 이름은 건드리지 않는다.
      const next = window.prompt(
        "새 표시 이름을 입력하세요.\n(실제 폴더/저장소 이름은 바뀌지 않습니다)",
        mount.alias,
      );
      if (!next || next.trim() === "" || next.trim() === mount.alias) return;
      setRemoveError(null);
      try {
        await controlApi.renameMount(workspace.id, mount.id, next.trim());
        await refresh();
      } catch (cause) {
        console.error(cause);
        setRemoveError(
          "이름을 바꾸지 못했습니다. 같은 이름이 이미 있거나 권한이 없습니다.",
        );
      }
    },
    [controlApi, refresh, workspace.id],
  );

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
        // OWNER 안내는 권한 거부(403)일 때만 맞는 말이다. 다른 실패에 그
        // 문구를 붙이면 사용자가 엉뚱한 원인을 의심하게 된다.
        const status =
          typeof cause === "object" && cause !== null && "status" in cause
            ? (cause as { status: number }).status
            : null;
        setRemoveError(
          status === 403
            ? "감시를 중단할 권한이 없습니다. 이 워크스페이스의 OWNER 인지 확인해 주세요."
            : "감시를 중단하지 못했습니다. 잠시 후 다시 시도해 주세요.",
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
        onRename={renameMount}
        loadFiles={(mount) => sourcesApi.listTrackedFiles(mount.id)}
      />
      {removeError && <p style={{ color: "red" }}>{removeError}</p>}

      {progress && progress.total > 0 && (
        <div className="analysis-progress">
          {progress.pending + progress.processing > 0 ? (
            <p className="analysis-progress__label">
              검토 중… {progress.done + progress.failed}/{progress.total} 완료
              {progress.processing > 0 && ` (지금 ${progress.processing}건 분석 중)`}
            </p>
          ) : (
            <p className="analysis-progress__label">
              검토 완료 — {progress.done}건
              {progress.failed > 0 && `, 실패 ${progress.failed}건`}
            </p>
          )}
          <div
            className="analysis-progress__bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done + progress.failed}
          >
            <div
              className="analysis-progress__fill"
              style={{
                width: `${Math.round(((progress.done + progress.failed) / progress.total) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      <p>
        <button type="button" onClick={() => void retryFailed()} disabled={retryBusy}>
          {retryBusy ? "다시 시작하는 중…" : "실패·미결 분석 다시 실행"}
        </button>
        {retryMessage && <span> {retryMessage}</span>}
      </p>

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
            onReuseDriveConnection={
              driveConnectionId
                ? () => {
                    const next = {
                      connectionId: driveConnectionId,
                      provider: "google_drive",
                    };
                    writePending(workspace.id, next);
                    setPending(next);
                  }
                : undefined
            }
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
