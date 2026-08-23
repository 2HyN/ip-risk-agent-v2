import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useSession } from "../auth/session.js";
import { ApiFailure } from "../shared/api/client.js";
import type { ConnectedSource, TrackedArtifact } from "../shared/api/types.js";
import { useResource } from "../shared/hooks/use-resource.js";
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

export function SourcePanel({ platform }: { platform: PlatformAdapter }) {
  const { api } = useSession();
  const { workspace, role } = useWorkspace();
  const sourceApi = useMemo(() => new SourceApiClient(api.client), [api]);
  const [search, setSearch] = useSearchParams();
  const sourcePath = useParams()["*"] ?? "";
  const [selected, setSelected] = useState<SourceProviderType | null>(null);
  const [managedDrive, setManagedDrive] = useState<ConnectedSource | null>(null);
  const [managedGithub, setManagedGithub] = useState<ConnectedSource | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<Error | null>(null);
  const sources = useResource(() => api.dataAccess(workspace.id), [api, workspace.id]);
  const provider = safeProvider(search.get("provider"));
  const connectionId = safeOpaqueId(search.get("connection_id"));
  const completion = search.get("status") === "connected" && provider !== null && connectionId !== null;

  const [reanalyzing, setReanalyzing] = useState<string | null>(null);
  const [untracking, setUntracking] = useState<string | null>(null);

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

  async function untrack(artifact: TrackedArtifact): Promise<void> {
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
    setManagedDrive(null);
    setSearch({}, { replace: true });
    sources.reload();
  }

  async function disableMount(mountId: string): Promise<void> {
    setMutationError(null);
    try {
      await api.disableMount(workspace.id, mountId);
      setNotice("Source mount가 비활성화되었습니다.");
      sources.reload();
    } catch (reason) {
      setMutationError(reason instanceof Error ? reason : new Error("Mount를 비활성화하지 못했습니다."));
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
  const artifactId = sourcePath.startsWith("artifacts/")
    ? sourcePath.slice("artifacts/".length)
    : null;
  if (artifactId !== null) {
    const artifact = trackedArtifacts.find((item) => item.artifact_id === artifactId);
    return <TrackedArtifactDetail workspaceId={workspace.id} artifact={artifact ?? null} />;
  }

  return (
    <div className="content content--wide">
      <PageHeader
        eyebrow="Source Plane"
        title="Connected sources"
        description="선택한 provider scope만 추적하며 원문은 이 화면에 표시하거나 저장하지 않습니다."
      />
      {notice === null ? null : <p className="source-success" role="status">{notice}</p>}
      {mutationError === null ? null : <ErrorState error={mutationError} />}
      <div className="source-layout">
        <div className="source-list">
          {connected.length === 0 ? (
            <Card>
              <EmptyState
                title="No connected source"
                description="Google Drive, GitHub 또는 Desktop local folder를 현재 workspace에 연결하세요."
              />
            </Card>
          ) : connected.map((source) => {
            const trackedFolderId = driveFolderId(source);
            return (
            <Card key={source.mount_id} className="source-card">
              <div className="card-row">
                <div>
                  <p className="eyebrow">{source.source_type ?? "SOURCE"}</p>
                  <h2>{source.source_type === "GOOGLE_DRIVE" ? "Google Drive" : source.alias}</h2>
                  <p>{source.provider_account_label ?? "Provider identity protected"}</p>
                  {source.source_type === "GOOGLE_DRIVE" ? (
                    <>
                      <p>{trackedFolderId === null ? "No folder tracked" : "1 folder tracked"}</p>
                      {trackedFolderId === null ? null : (
                        <ul aria-label="Tracked Google Drive folder">
                          <li>{trackedFolderId}</li>
                        </ul>
                      )}
                    </>
                  ) : null}
                </div>
                <Badge tone={toneFor(source.status)}>{source.status}</Badge>
              </div>
              <div className="button-row">
                {source.source_type === "GOOGLE_DRIVE" && source.status === "ACTIVE" ? (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setManagedDrive(source);
                      setSelected(null);
                      setMutationError(null);
                    }}
                  >
                    Add files
                  </Button>
                ) : null}
                {source.source_type === "GITHUB" && source.status === "ACTIVE" ? (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setManagedGithub(source);
                      setManagedDrive(null);
                      setSelected(null);
                      setMutationError(null);
                    }}
                  >
                    Add repository
                  </Button>
                ) : null}
                {source.status === "REAUTH_REQUIRED" && source.source_type !== "LOCAL" ? (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setSelected(source.source_type as SourceProviderType)}
                  >
                    Reconnect
                  </Button>
                ) : null}
                {role === "OWNER" && source.status !== "DISABLED" ? (
                  <Button type="button" variant="danger" onClick={() => void disableMount(source.mount_id)}>
                    Disable
                  </Button>
                ) : null}
              </div>
            </Card>
            );
          })}
          <section className="source-artifacts" aria-labelledby="tracked-artifacts-title">
            <div>
              <p className="eyebrow">Virtual Workspace</p>
              <h2 id="tracked-artifacts-title">Tracked artifacts</h2>
              <p>Provider files that have entered the snapshot and analysis pipeline.</p>
            </div>
            {trackedArtifacts.length === 0 ? (
              <Card>
                <EmptyState
                  title="Waiting for the first snapshot"
                  description={connected.length === 0
                    ? "Connect a source to begin tracking artifacts."
                    : "The source is connected. Newly selected or changed artifacts will appear here as collection begins."}
                />
              </Card>
            ) : trackedArtifacts.map((artifact) => (
              <Card key={artifact.artifact_id} className="source-card">
                <div className="card-row">
                  <div>
                    <p className="eyebrow">{artifact.source_type}</p>
                    <h3>{artifact.display_name}</h3>
                    <p>{artifact.logical_path}</p>
                    <p>Change: {artifact.change_status ?? "WAITING"} · Analysis: {artifact.analysis_status ?? "WAITING"}</p>
                    <p>{artifact.active_risk_count} active · {artifact.risk_count} total risks</p>
                  </div>
                  <Badge tone={toneFor(artifact.analysis_status ?? artifact.availability)}>
                    {artifact.analysis_status ?? artifact.availability}
                  </Badge>
                </div>
                {(() => {
                  // 실패를 상태 배지 하나로만 두면 "왜" 를 알 수 없다. 특히 provider
                  // 한도 소진은 다시 눌러도 같으므로 그 사실을 말해 주어야 한다.
                  const notice = analysisFailureNotice(artifact.analysis_failure_safe);
                  if (notice === null) return null;
                  return (
                    <p className={`analysis-notice analysis-notice--${notice.tone}`} role="status">
                      <strong>{notice.title}</strong> {notice.detail}
                    </p>
                  );
                })()}
                {artifact.first_risk_id === null ? (
                  <p>No risk has been produced for the latest analyzed state.</p>
                ) : (
                  <span>{artifact.highest_risk_priority} priority</span>
                )}
                <div className="card-actions">
                  <Link to={`artifacts/${encodeURIComponent(artifact.artifact_id)}`}>
                    View artifact analysis
                  </Link>
                  {artifact.change_event_id === null ? null : (
                    <Button
                      type="button"
                      onClick={() => void reanalyze(artifact)}
                      disabled={reanalyzing !== null}
                    >
                      {reanalyzing === artifact.artifact_id ? "재검사 요청 중…" : "다시 검사"}
                    </Button>
                  )}
                  {artifact.source_type === "GOOGLE_DRIVE" ? (
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => void untrack(artifact)}
                      disabled={untracking !== null}
                    >
                      {untracking === artifact.artifact_id
                        ? "추적 해제 중…"
                        : "추적 해제"}
                    </Button>
                  ) : null}
                </div>
              </Card>
            ))}
          </section>
        </div>
        <div className="source-connect-stack">
          <Card>
            <AddSourceChooser
              onSelect={setSelected}
              onUseExistingGithub={
                activeGithub === undefined
                  ? null
                  : () => {
                      setManagedGithub(activeGithub);
                      setManagedDrive(null);
                      setMutationError(null);
                    }
              }
              isDesktop={platform.platform === "desktop"}
              riskWorkspaceId={workspace.id}
              connectionApiClient={sourceApi}
            />
          </Card>
          {managedDrive !== null
          || managedGithub !== null
          || completion
          || selected === "LOCAL"
          || selected === "GOOGLE_DRIVE" ? <Card>
          {managedGithub !== null ? (
            <GitHubCompletion
              sourceApi={sourceApi}
              mountId={managedGithub.mount_id}
              riskWorkspaceId={workspace.id}
              onComplete={() => complete("GitHub repository를 추가로 연결했습니다.")}
            />
          ) : managedDrive !== null || selected === "GOOGLE_DRIVE" || (completion && provider === "GOOGLE_DRIVE") ? (
            <DriveFolderShare
              sourceApi={sourceApi}
              trackedFolderId={managedDrive === null ? null : driveFolderId(managedDrive)}
              riskWorkspaceId={workspace.id}
              onComplete={(count) =>
                complete(
                  count === 0
                    ? "폴더를 붙였습니다. 안에 파일이 없어 아직 추적할 것이 없습니다."
                    : `폴더를 붙였습니다. 파일 ${count}개를 추적합니다.`,
                )
              }
            />
          ) : completion && provider === "GITHUB" ? (
            <GitHubCompletion
              sourceApi={sourceApi}
              connectionId={connectionId}
              riskWorkspaceId={workspace.id}
              onComplete={() => complete("GitHub repository가 연결되었습니다.")}
            />
          ) : selected === "LOCAL" ? (
            <ConnectLocalSource
              platform={platform}
              riskWorkspaceId={workspace.id}
              issueEnrollmentChallenge={() => sourceApi.issueDesktopEnrollmentChallenge()}
              revokeDesktopDevice={(deviceId) => sourceApi.revokeDesktopDevice(deviceId)}
              onConnected={() => complete("Local folder가 연결되고 watcher가 시작되었습니다.")}
            />
          ) : null}
          </Card> : null}
        </div>
      </div>
    </div>
  );
}

function TrackedArtifactDetail({
  workspaceId,
  artifact,
}: {
  workspaceId: string;
  artifact: TrackedArtifact | null;
}) {
  if (artifact === null) {
    return (
      <div className="content">
        <PageHeader eyebrow="Virtual Workspace" title="Artifact unavailable" />
        <Card>
          <EmptyState
            title="Tracked artifact not found"
            description="This artifact is not available in the current workspace."
          />
          <Link to={`/w/${encodeURIComponent(workspaceId)}/sources`}>Back to Sources</Link>
        </Card>
      </div>
    );
  }
  return (
    <div className="content">
      <PageHeader
        eyebrow="Virtual Workspace artifact"
        title={artifact.display_name}
        description={`${artifact.source_type} · ${artifact.source_context ?? "Connected source"}`}
      />
      <Card>
        <dl className="detail-grid">
          <div><dt>Path</dt><dd>{artifact.logical_path}</dd></div>
          <div><dt>Availability</dt><dd>{artifact.availability}</dd></div>
          <div><dt>Latest revision</dt><dd>{artifact.latest_revision ?? "Waiting"}</dd></div>
          <div><dt>Change</dt><dd>{artifact.change_status ?? "WAITING"}</dd></div>
          <div><dt>Analysis</dt><dd>{artifact.analysis_status ?? "WAITING"}</dd></div>
          <div><dt>Risk</dt><dd>{artifact.risk_count === 0
            ? "No risk produced"
            : `${artifact.active_risk_count} active / ${artifact.risk_count} total (${artifact.highest_risk_priority ?? "review"})`}</dd></div>
          <div><dt>Last updated</dt><dd>{artifact.updated_at}</dd></div>
        </dl>
        <div className="button-row">
          <Link to={`/w/${encodeURIComponent(workspaceId)}/sources`}>Back to Sources</Link>
          {artifact.first_risk_id === null ? null : (
            <Link to={`/w/${encodeURIComponent(workspaceId)}/risks/${encodeURIComponent(artifact.first_risk_id)}`}>
              Open risk findings and evidence
            </Link>
          )}
        </div>
      </Card>
    </div>
  );
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
  trackedFolderId = null,
  onComplete,
}: {
  sourceApi: SourceApiClient;
  riskWorkspaceId: string;
  trackedFolderId?: string | null;
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
        Drive 에서 폴더를 열고 아래 주소를 <strong>뷰어</strong>로 공유한 뒤, 그 폴더 주소를
        붙여 넣으세요. 공유한 폴더 안만 보이고, 무엇을 넣을지는 직접 정하시면 됩니다.
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
          if (trackedFolderId !== null && folderReference.trim().includes(trackedFolderId)) {
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
 */
function GitHubCompletion({
  sourceApi,
  connectionId,
  mountId,
  riskWorkspaceId,
  onComplete,
}: {
  sourceApi: SourceApiClient;
  connectionId?: string;
  mountId?: string;
  riskWorkspaceId: string;
  onComplete: () => void;
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
      <p className="eyebrow">GitHub App installed</p>
      <h2>{mountId === undefined ? "Select repository and branch" : "Add another repository"}</h2>
      <p>
        아래 목록은 이 설치에서 접근할 수 있는 저장소입니다. 원하는 저장소가 없으면
        GitHub 에서 설치에 추가한 뒤 다시 열어 주세요.
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
      <Button type="button" disabled={repository === null || !branch.trim() || busy} onClick={() => void mount()}>
        Connect repository
      </Button>
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
