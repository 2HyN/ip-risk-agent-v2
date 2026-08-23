import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useSession } from "../auth/session.js";
import { ApiFailure } from "../shared/api/client.js";
import type { ConnectedSource, TrackedArtifact } from "../shared/api/types.js";
import { useResource } from "../shared/hooks/use-resource.js";
import { useAnalysisProgress } from "../shared/hooks/use-analysis-progress.js";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  Select,
  Input,
  toneFor,
} from "../shared/ui/index.js";
import { analysisFailureNotice } from "../shared/analysis-failure.js";
import { useWorkspace } from "../workspace/workspace-context.js";
import { AddSourceChooser, type SourceProviderType } from "./AddSourceChooser.js";
import { ConnectLocalSource } from "./ConnectLocalSource.js";
import {
  SourceApiClient,
  type GitHubRepository,
} from "./api/connectionClient.js";
import type { PlatformAdapter } from "./platform/PlatformAdapter.js";

/**
 * Files — 마운트한 폴더들을 하나의 통합 디렉토리로 보여 준다.
 *
 * 마운트는 **폴더 단위**다. 마운트한 폴더가 이 화면의 뿌리에 붙고, 그 안은 실제
 * 소스의 폴더 구조를 그대로 반영한다. 원문은 이 화면에 표시하거나 저장하지 않는다 —
 * 보이는 것은 이름 · 경로 · 상태뿐이다.
 */
export function SourcePanel({ platform }: { platform: PlatformAdapter }) {
  const { api } = useSession();
  const { workspace, role } = useWorkspace();
  const sourceApi = useMemo(() => new SourceApiClient(api.client), [api]);
  const [search, setSearch] = useSearchParams();
  const [selected, setSelected] = useState<SourceProviderType | null>(null);
  const [managedGithub, setManagedGithub] = useState<ConnectedSource | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<Error | null>(null);
  // 탐색 위치 — [] 는 뿌리(마운트 목록), 첫 칸은 mount_id, 나머지는 폴더 이름.
  const [dirPath, setDirPath] = useState<string[]>([]);
  const sources = useResource(() => api.dataAccess(workspace.id), [api, workspace.id]);
  const provider = safeProvider(search.get("provider"));
  const connectionId = safeOpaqueId(search.get("connection_id"));
  const completion = search.get("status") === "connected" && provider !== null && connectionId !== null;

  const [reanalyzing, setReanalyzing] = useState<string | null>(null);

  // 작업 현황 — worker 가 밖에서 돌므로 주기적으로 묻고, 끝난 문서 수가 변하면
  // 목록도 다시 읽는다. 그래야 "검사 중" 배지가 손을 대지 않아도 걷힌다.
  const loadProgress = useCallback(
    () => api.analysesProgress(workspace.id),
    [api, workspace.id],
  );
  const progress = useAnalysisProgress(loadProgress);
  const doneCount =
    progress === null
      ? null
      : progress.succeeded + progress.failed + progress.inconclusive;
  const lastDone = useRef<number | null>(null);
  const reloadSources = sources.reload;
  useEffect(() => {
    if (doneCount === null) return;
    if (lastDone.current !== null && doneCount !== lastDone.current) {
      reloadSources();
    }
    lastDone.current = doneCount;
  }, [doneCount, reloadSources]);

  async function reanalyze(artifact: TrackedArtifact): Promise<void> {
    if (artifact.change_event_id === null) return;
    setReanalyzing(artifact.artifact_id);
    setNotice(null);
    setMutationError(null);
    try {
      await api.requestReanalysis(workspace.id, artifact.change_event_id);
      setNotice(`${artifact.display_name} 재검사를 요청했습니다.`);
      sources.reload();
    } catch (reason) {
      setMutationError(
        reason instanceof Error ? reason : new Error("재검사를 요청하지 못했습니다."),
      );
    } finally {
      setReanalyzing(null);
    }
  }

  function untrack(artifact: TrackedArtifact): void {
    // 폴더를 보는 지금 "이 파일만 추적 해제" 는 성립하지 않는다 (§6.1 · 1-F).
    // 범위에서 뺄 방법이 없고, Risk 만 닫아 두면 그 파일의 다음 변경에 되살아난다.
    // 추적을 끊는 방법은 하나뿐이라 그것을 말해 준다.
    window.alert(
      `${artifact.display_name} 의 추적을 끊으려면 ` +
        "공유 폴더 밖으로 옮기세요. " +
        "옮기면 지금까지의 Risk 와 근거는 지워지지 않고 '제외됨' 으로 닫힙니다. " +
        "다시 폴더에 넣으면 검토해 두신 판단 그대로 되살아납니다.",
    );
  }

  function complete(message: string): void {
    setNotice(message);
    setMutationError(null);
    setSelected(null);
    setManagedGithub(null);
    setAddOpen(false);
    setSearch({}, { replace: true });
    sources.reload();
  }

  function closeDialog(): void {
    setSelected(null);
    setManagedGithub(null);
    setAddOpen(false);
    if (completion) setSearch({}, { replace: true });
  }

  async function disableMount(mountId: string): Promise<void> {
    setMutationError(null);
    try {
      await api.disableMount(workspace.id, mountId);
      setNotice("Source mount가 비활성화되었습니다.");
      setDirPath([]);
      sources.reload();
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason : new Error("Mount를 비활성화하지 못했습니다."));
    }
  }

  async function startInstall(): Promise<void> {
    try {
      const { authorizeUrl } = await sourceApi.startGithubConnection(workspace.id);
      window.location.assign(authorizeUrl);
    } catch {
      setMutationError(new Error("GitHub 연결을 시작하지 못했습니다."));
    }
  }

  if (sources.loading) return <LoadingState label="Loading connected sources" />;
  if (sources.error !== null) return <ErrorState error={sources.error} retry={sources.reload} />;
  const connected = sources.data?.connected_sources ?? [];
  // 살아 있는 GitHub 연결. 있으면 "Add Source" 가 설치 화면으로 나가지 않는다.
  const activeGithub = connected.find(
    (item) => item.source_type === "GITHUB" && item.status === "ACTIVE",
  );
  const trackedArtifacts = sources.data?.tracked_artifacts ?? [];
  const trackedDriveFolderIds = connected
    .filter((item) => item.source_type === "GOOGLE_DRIVE")
    .map(driveFolderId)
    .filter((value): value is string => value !== null);

  const currentMount =
    dirPath.length === 0
      ? null
      : connected.find((item) => item.mount_id === dirPath[0]) ?? null;
  const listing =
    currentMount === null
      ? null
      : listDirectory(trackedArtifacts, currentMount.mount_id, dirPath.slice(1));

  const dialogOpen =
    addOpen || managedGithub !== null || completion || selected !== null;
  const active = progress === null ? 0 : progress.queued + progress.running;
  const percent =
    progress === null || progress.total === 0
      ? null
      : Math.round(((doneCount ?? 0) / progress.total) * 100);

  return (
    <div className="content content--wide">
      <PageHeader
        eyebrow="Workspace files"
        title="Files"
        description="마운트는 폴더 단위입니다. 마운트한 폴더가 이 목록의 뿌리에 붙고, 안의 구조는 실제 소스를 그대로 따릅니다. 원문은 표시하거나 저장하지 않습니다."
        actions={
          <Button type="button" onClick={() => { setAddOpen(true); setMutationError(null); }}>
            Add source
          </Button>
        }
      />
      {progress !== null && progress.total > 0 ? (
        <div className="progress-strip" role="status" aria-label="Analysis progress">
          <div
            className="progress"
            role="progressbar"
            aria-valuenow={percent ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="progress__bar" style={{ width: `${percent ?? 0}%` }} />
          </div>
          <span className="progress__caption">
            {active > 0
              ? `검사 중 ${active}건 · ${doneCount}/${progress.total} 완료`
              : progress.failed > 0
                ? `${doneCount}/${progress.total} 완료 · 실패 ${progress.failed}건`
                : `${progress.total}개 문서 검사 완료`}
          </span>
        </div>
      ) : null}
      {notice === null ? null : <p className="source-success" role="status">{notice}</p>}
      {mutationError === null ? null : <ErrorState error={mutationError} />}

      <Card className="explorer">
        <nav className="breadcrumbs" aria-label="File path">
          <button type="button" onClick={() => setDirPath([])} disabled={dirPath.length === 0}>
            Files
          </button>
          {currentMount === null ? null : (
            <>
              <span aria-hidden="true">/</span>
              <button
                type="button"
                onClick={() => setDirPath([currentMount.mount_id])}
                disabled={dirPath.length === 1}
              >
                {currentMount.alias}
              </button>
            </>
          )}
          {dirPath.slice(1).map((segment, index) => (
            <span key={`${segment}-${index}`} className="breadcrumbs__part">
              <span aria-hidden="true">/</span>
              <button
                type="button"
                onClick={() => setDirPath(dirPath.slice(0, index + 2))}
                disabled={index === dirPath.length - 2}
              >
                {segment}
              </button>
            </span>
          ))}
        </nav>

        {dirPath.length === 0 ? (
          connected.length === 0 ? (
            <EmptyState
              title="No connected source"
              description="Add source에서 Google Drive 폴더, GitHub repository 또는 Desktop local folder를 연결하세요. 마운트는 파일이 아니라 폴더 단위입니다."
            />
          ) : (
            <ul className="explorer-list">
              {connected.map((source) => {
                const fileCount = trackedArtifacts.filter(
                  (item) => item.mount_id === source.mount_id,
                ).length;
                return (
                  <li key={source.mount_id} className="explorer-row">
                    <button
                      type="button"
                      className="explorer-row__main"
                      onClick={() => setDirPath([source.mount_id])}
                    >
                      <span className="explorer-icon" aria-hidden="true">📁</span>
                      <span className="explorer-row__name">{source.alias}</span>
                      <span className="explorer-row__meta">
                        {providerLabel(source.source_type)} · 파일 {fileCount}개
                      </span>
                    </button>
                    <span className="explorer-row__side">
                      <Badge tone={toneFor(source.status)}>{source.status}</Badge>
                      {role === "OWNER" && source.status !== "DISABLED" ? (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => void disableMount(source.mount_id)}
                        >
                          Disable
                        </Button>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          )
        ) : listing === null ? (
          <EmptyState
            title="Folder unavailable"
            description="이 mount는 더 이상 이 workspace에 없습니다."
          />
        ) : listing.directories.length === 0 && listing.files.length === 0 ? (
          <EmptyState
            title="Empty folder"
            description="이 폴더에서 추적 중인 파일이 아직 없습니다. 파일을 소스 폴더에 넣으면 자동으로 나타납니다."
          />
        ) : (
          <ul className="explorer-list">
            {listing.directories.map((directory) => (
              <li key={directory} className="explorer-row">
                <button
                  type="button"
                  className="explorer-row__main"
                  onClick={() => setDirPath([...dirPath, directory])}
                >
                  <span className="explorer-icon" aria-hidden="true">📁</span>
                  <span className="explorer-row__name">{directory}</span>
                </button>
              </li>
            ))}
            {listing.files.map((artifact) => {
              const failure = analysisFailureNotice(artifact.analysis_failure_safe);
              return (
                <li key={artifact.artifact_id} className="explorer-row explorer-row--file">
                  <div className="explorer-row__main">
                    <span className="explorer-icon" aria-hidden="true">📄</span>
                    <span className="explorer-row__name">{artifact.display_name}</span>
                    <span className="explorer-row__meta">
                      Analysis: {artifact.analysis_status ?? "WAITING"}
                      {artifact.risk_count > 0
                        ? ` · Risk ${artifact.active_risk_count}/${artifact.risk_count}`
                        : ""}
                    </span>
                  </div>
                  <span className="explorer-row__side">
                    {artifact.first_risk_id === null ? null : (
                      <Link
                        className="text-link"
                        to={`/w/${workspace.id}/risks/${encodeURIComponent(artifact.first_risk_id)}`}
                      >
                        Review →
                      </Link>
                    )}
                    <Badge tone={toneFor(artifact.analysis_status ?? artifact.availability)}>
                      {artifact.analysis_status ?? artifact.availability}
                    </Badge>
                    {artifact.change_event_id === null ? null : (
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => void reanalyze(artifact)}
                        disabled={reanalyzing !== null}
                      >
                        {reanalyzing === artifact.artifact_id ? "재검사 요청 중…" : "다시 검사"}
                      </Button>
                    )}
                    {artifact.source_type === "GOOGLE_DRIVE" ? (
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => untrack(artifact)}
                      >
                        추적 해제
                      </Button>
                    ) : null}
                  </span>
                  {failure === null ? null : (
                    <p
                      className={`analysis-notice analysis-notice--${failure.tone}`}
                      role="status"
                    >
                      <strong>{failure.title}</strong> {failure.detail}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {dialogOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeDialog}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Add source"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal__head">
              <Button type="button" variant="ghost" onClick={closeDialog}>
                닫기 ✕
              </Button>
            </div>
            {managedGithub !== null ? (
              <GitHubCompletion
                sourceApi={sourceApi}
                mountId={managedGithub.mount_id}
                riskWorkspaceId={workspace.id}
                onComplete={() => complete("GitHub repository를 추가로 연결했습니다.")}
                onInstallMore={() => {
                  void startInstall();
                }}
              />
            ) : completion && provider === "GITHUB" ? (
              <GitHubCompletion
                sourceApi={sourceApi}
                connectionId={connectionId ?? undefined}
                riskWorkspaceId={workspace.id}
                onComplete={() => complete("GitHub repository가 연결되었습니다.")}
                onInstallMore={() => {
                  void startInstall();
                }}
              />
            ) : selected === "GOOGLE_DRIVE" || (completion && provider === "GOOGLE_DRIVE") ? (
              <DriveFolderShare
                sourceApi={sourceApi}
                trackedFolderIds={trackedDriveFolderIds}
                riskWorkspaceId={workspace.id}
                onComplete={(count) =>
                  complete(
                    count === 0
                      ? "폴더를 붙였습니다. 안에 파일이 없어 아직 추적할 것이 없습니다."
                      : `폴더를 붙였습니다. 파일 ${count}개를 추적합니다.`,
                  )
                }
              />
            ) : selected === "LOCAL" ? (
              <ConnectLocalSource
                platform={platform}
                riskWorkspaceId={workspace.id}
                issueEnrollmentChallenge={() => sourceApi.issueDesktopEnrollmentChallenge()}
                revokeDesktopDevice={(deviceId) => sourceApi.revokeDesktopDevice(deviceId)}
                onConnected={() => complete("Local folder가 연결되고 watcher가 시작되었습니다.")}
              />
            ) : (
              <AddSourceChooser
                onSelect={setSelected}
                onUseExistingGithub={
                  activeGithub === undefined
                    ? null
                    : () => {
                        setManagedGithub(activeGithub);
                      }
                }
                isDesktop={platform.platform === "desktop"}
                riskWorkspaceId={workspace.id}
                connectionApiClient={sourceApi}
              />
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 한 mount 안에서 지금 위치의 하위 폴더와 파일. 경로는 `별칭/상대경로` 다. */
function listDirectory(
  artifacts: TrackedArtifact[],
  mountId: string,
  segments: string[],
): { directories: string[]; files: TrackedArtifact[] } {
  const directories = new Set<string>();
  const files: TrackedArtifact[] = [];
  for (const artifact of artifacts) {
    if (artifact.mount_id !== mountId) continue;
    // 첫 칸은 mount 별칭이라 화면의 뿌리와 같은 것 — 버린다. 별칭 없이 온 옛
    // 경로는 이름 하나짜리 파일로 취급한다.
    const relative = artifact.logical_path.includes("/")
      ? artifact.logical_path.split("/").slice(1)
      : [artifact.logical_path];
    const inside =
      relative.length > segments.length &&
      segments.every((segment, index) => relative[index] === segment);
    if (!inside) continue;
    const rest = relative.slice(segments.length);
    const head = rest[0];
    if (rest.length === 1) files.push(artifact);
    else if (head !== undefined) directories.add(head);
  }
  files.sort((a, b) => a.display_name.localeCompare(b.display_name));
  return { directories: [...directories].sort(), files };
}

function providerLabel(sourceType: string | null): string {
  if (sourceType === "GOOGLE_DRIVE") return "Google Drive";
  if (sourceType === "GITHUB") return "GitHub";
  if (sourceType === "LOCAL") return "Local";
  return "Source";
}

/**
 * 폴더를 공유받아 붙인다 — D1.
 *
 * Picker 를 대신한다. Picker 의 폴더 선택은 **폴더 객체만** 주었고 그 안은 못
 * 읽었다 (결함 41). 화면이 하는 일은 둘이다 — 어디로 공유할지 알려 주고, 붙인 뒤
 * **몇 개를 찾았는지** 말한다. 뒤엣것이 없으면 빈 폴더와 못 읽는 폴더가 똑같이
 * 아무것도 아닌 것으로 보인다 (결함 40).
 */
function DriveFolderShare({
  sourceApi,
  riskWorkspaceId,
  trackedFolderIds = [],
  onComplete,
}: {
  sourceApi: SourceApiClient;
  riskWorkspaceId: string;
  trackedFolderIds?: string[];
  onComplete: (trackedFileCount: number) => void;
}) {
  const [address, setAddress] = useState<string | null>(null);
  const [folderReference, setFolderReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void sourceApi
      .driveSharingRuntimeConfig()
      .then((config) => {
        if (!cancelled) setAddress(config.sharingAddress);
      })
      .catch(() => {
        if (!cancelled) setAddress(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceApi]);

  async function submit(): Promise<void> {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const mount = await sourceApi.mountSharedDriveFolder(riskWorkspaceId, folderReference.trim());
      onComplete(mount.trackedFileCount ?? 0);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  /** 서버가 무엇을 해야 하는지 말해 줬으면 그대로 보여 준다. 다시 쓰지 않는다. */
  function messageFor(reason: unknown): string {
    if (reason instanceof ApiFailure) {
      const detail = reason.detail;
      if (typeof detail === "object" && detail !== null && typeof detail.message === "string") {
        return detail.message;
      }
      if (reason.status === 409) return "이 폴더가 아직 공유되지 않았습니다.";
    }
    return "폴더를 붙이지 못했습니다. 주소를 다시 확인해 주세요.";
  }

  return (
    <div className="source-completion">
      <p className="eyebrow">Google Drive</p>
      <h2>추적할 폴더를 공유해 주세요</h2>
      <p>
        마운트는 <strong>파일이 아니라 폴더 단위</strong>입니다. Drive 에서 폴더를 열고
        아래 주소를 <strong>뷰어</strong>로 공유한 뒤, 그 폴더 주소를 붙여 넣으세요.
        공유한 폴더 안만 보이고, 무엇을 넣을지는 직접 정하시면 됩니다.
      </p>
      {address === null ? (
        <p className="source-error">공유 주소를 아직 불러오지 못했습니다.</p>
      ) : (
        <p className="source-selection">
          <code>{address}</code>{" "}
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              void navigator.clipboard?.writeText(address);
              setCopied(true);
            }}
          >
            {copied ? "복사됨" : "주소 복사"}
          </Button>
        </p>
      )}
      <label className="source-field">
        <span>폴더 주소</span>
        <input
          type="text"
          value={folderReference}
          placeholder="https://drive.google.com/drive/folders/..."
          aria-label="Drive folder link"
          onChange={(event) => {
            setFolderReference(event.target.value);
            setError(null);
          }}
        />
      </label>
      <Button
        type="button"
        disabled={busy || folderReference.trim().length === 0}
        onClick={() => {
          const reference = folderReference.trim();
          if (trackedFolderIds.some((id) => reference.includes(id))) {
            setInfo("이 폴더는 이미 추적하고 있습니다.");
            return;
          }
          void submit();
        }}
      >
        {busy ? "폴더를 확인하는 중" : "폴더 붙이기"}
      </Button>
      {error === null ? null : <p className="source-error" role="alert">{error}</p>}
      {info === null ? null : <p className="source-selection" role="status">{info}</p>}
    </div>
  );
}

/**
 * 설치에서 접근 가능한 저장소를 보여 주고 고른 것을 mount 로 만든다.
 *
 * 방금 설치를 마치고 돌아왔으면 `connectionId` 로, 이미 붙어 있는 GitHub 연결에
 * 저장소를 **더** 붙이는 것이면 `mountId` 로 온다. 뒤엣것이 없으면 저장소를 하나
 * 붙인 뒤 다음 것을 붙일 길이 없다 — GitHub 은 저장소 선택이 바뀔 때만 되돌려
 * 보내므로 설치 화면을 다시 거치는 것으로는 돌아오지 못한다.
 *
 * 그래서 redirect 는 설치에 저장소를 **추가**할 때 한 번뿐이다. 설치에 이미 있는
 * 저장소는 이 창에서 몇 개든 redirect 없이 각각 mount 로 만들 수 있다.
 */
function GitHubCompletion({
  sourceApi,
  connectionId,
  mountId,
  riskWorkspaceId,
  onComplete,
  onInstallMore,
}: {
  sourceApi: SourceApiClient;
  connectionId?: string;
  mountId?: string;
  riskWorkspaceId: string;
  onComplete: () => void;
  onInstallMore?: () => void;
}) {
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [branch, setBranch] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = mountId === undefined
      ? sourceApi.githubRepositories(connectionId ?? "")
      : sourceApi.githubRepositoriesForMount(mountId);
    void load.then((items) => {
      if (!active) return;
      setRepositories(items);
      const first = items[0];
      if (first !== undefined) {
        setSelectedId(String(first.id));
        setBranch(first.defaultBranch);
      }
    }).catch(() => active && setError("설치에서 접근 가능한 repository를 불러오지 못했습니다.")).finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [connectionId, mountId, sourceApi]);

  const repository = repositories.find((item) => String(item.id) === selectedId) ?? null;

  async function mount(): Promise<void> {
    if (repository === null || !branch.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (mountId === undefined) {
        await sourceApi.createGithubMount(connectionId ?? "", riskWorkspaceId, repository, branch.trim());
      } else {
        await sourceApi.createGithubMountForMount(mountId, riskWorkspaceId, repository, branch.trim());
      }
      onComplete();
    } catch {
      setError("선택한 repository/branch를 mount로 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="source-completion">
      <p className="eyebrow">GitHub App</p>
      <h2>{mountId === undefined ? "Select repository and branch" : "Add another repository"}</h2>
      <p>
        아래 목록은 GitHub App 설치에서 접근할 수 있는 저장소입니다. 여기 있는
        저장소는 redirect 없이 바로 연결됩니다.
      </p>
      <Field label="Repository">
        <Select
          value={selectedId}
          disabled={busy}
          onChange={(event) => {
            setSelectedId(event.target.value);
            const next = repositories.find((item) => String(item.id) === event.target.value);
            if (next !== undefined) setBranch(next.defaultBranch);
          }}
        >
          {repositories.map((item) => <option key={item.id} value={item.id}>{item.fullName}{item.private ? " · private" : ""}</option>)}
        </Select>
      </Field>
      <Field label="Tracked branch">
        <Input value={branch} onChange={(event) => setBranch(event.target.value)} />
      </Field>
      <div className="button-row">
        <Button type="button" disabled={repository === null || !branch.trim() || busy} onClick={() => void mount()}>
          Connect repository
        </Button>
        {/*
          설치에 없는 저장소를 붙이려면 GitHub 으로 가야 한다. App 이 스스로
          저장소 접근 권한을 얻는 API 는 없기 때문이다. 이 길을 없애면 설치에
          없는 저장소는 영영 붙일 수 없다.
        */}
        {onInstallMore === undefined ? null : (
          <Button type="button" variant="secondary" onClick={onInstallMore}>
            GitHub App에 repo 추가
          </Button>
        )}
      </div>
      {error === null ? null : <p className="source-error" role="alert">{error}</p>}
    </div>
  );
}

function safeProvider(value: string | null): "GOOGLE_DRIVE" | "GITHUB" | null {
  return value === "GOOGLE_DRIVE" || value === "GITHUB" ? value : null;
}

function safeOpaqueId(value: string | null): string | null {
  if (value === null || value.length < 8 || value.length > 256 || !/^[A-Za-z0-9._~-]+$/u.test(value)) return null;
  return value;
}

/** 이 마운트가 보는 폴더. 없으면 `null` (§6.1 · 1-F). */
function driveFolderId(source: ConnectedSource): string | null {
  const value = source.tracking_scope_summary.folder_id;
  return typeof value === "string" && value.length > 0 ? value : null;
}
