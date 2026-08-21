import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useSession } from "../auth/session.js";
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
import { useWorkspace } from "../workspace/workspace-context.js";
import { AddSourceChooser, type SourceProviderType } from "./AddSourceChooser.js";
import { ConnectLocalSource } from "./ConnectLocalSource.js";
import {
  SourceApiClient,
  type GitHubRepository,
} from "./api/connectionClient.js";
import type { DrivePickerAdapter, DrivePickerFile } from "./platform/DrivePickerAdapter.js";
import type { PlatformAdapter } from "./platform/PlatformAdapter.js";

export function SourcePanel({
  platform,
  drivePicker,
}: {
  platform: PlatformAdapter;
  drivePicker: DrivePickerAdapter;
}) {
  const { api } = useSession();
  const { workspace, role } = useWorkspace();
  const sourceApi = useMemo(() => new SourceApiClient(api.client), [api]);
  const [search, setSearch] = useSearchParams();
  const [selected, setSelected] = useState<SourceProviderType | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<Error | null>(null);
  const sources = useResource(() => api.dataAccess(workspace.id), [api, workspace.id]);
  const provider = safeProvider(search.get("provider"));
  const connectionId = safeOpaqueId(search.get("connection_id"));
  const completion = search.get("status") === "connected" && provider !== null && connectionId !== null;

  function complete(message: string): void {
    setNotice(message);
    setMutationError(null);
    setSelected(null);
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
          ) : connected.map((source) => (
            <Card key={source.mount_id} className="source-card">
              <div className="card-row">
                <div>
                  <p className="eyebrow">{source.source_type ?? "SOURCE"}</p>
                  <h2>{source.alias}</h2>
                  <p>{source.provider_account_label ?? "Provider identity protected"}</p>
                </div>
                <Badge tone={toneFor(source.status)}>{source.status}</Badge>
              </div>
              <div className="button-row">
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
          ))}
        </div>
        <Card className="source-connect-card">
          {completion && provider === "GOOGLE_DRIVE" ? (
            <DriveCompletion
              sourceApi={sourceApi}
              drivePicker={drivePicker}
              connectionId={connectionId}
              riskWorkspaceId={workspace.id}
              onComplete={() => complete("Google Drive files가 연결되었습니다.")}
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
          ) : (
            <AddSourceChooser
              onSelect={setSelected}
              isDesktop={platform.platform === "desktop"}
              riskWorkspaceId={workspace.id}
              connectionApiClient={sourceApi}
            />
          )}
        </Card>
      </div>
    </div>
  );
}

function DriveCompletion({
  sourceApi,
  drivePicker,
  connectionId,
  riskWorkspaceId,
  onComplete,
}: {
  sourceApi: SourceApiClient;
  drivePicker: DrivePickerAdapter;
  connectionId: string;
  riskWorkspaceId: string;
  onComplete: () => void;
}) {
  const [files, setFiles] = useState<DrivePickerFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(): Promise<void> {
    setBusy(true);
    setError(null);
    let selectedFiles: DrivePickerFile[];
    try {
      const accessToken = await sourceApi.createDrivePickerSession(connectionId);
      selectedFiles = await drivePicker.pick(accessToken);
    } catch {
      setError("Google Drive Picker 선택 결과를 확인하지 못했습니다. 다시 선택해 주세요.");
      setBusy(false);
      return;
    }
    setFiles(selectedFiles);
    if (selectedFiles.length === 0) {
      setBusy(false);
      return;
    }
    try {
      await sourceApi.createDriveMount(
        connectionId,
        riskWorkspaceId,
        selectedFiles.map((file) => file.id),
      );
      onComplete();
    } catch {
      setError("선택한 Drive 파일을 mount로 만들지 못했습니다.");
      setBusy(false);
    }
  }

  async function mount(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await sourceApi.createDriveMount(connectionId, riskWorkspaceId, files.map((file) => file.id));
      onComplete();
    } catch {
      setError("선택한 Drive 파일을 mount로 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="source-completion">
      <p className="eyebrow">Google Drive connected</p>
      <h2>Select files to track</h2>
      <p>Picker에서 Select하면 명시적으로 선택한 file ID만 즉시 tracking scope에 저장됩니다.</p>
      {!drivePicker.available ? <p className="source-error">Drive Picker runtime configuration is unavailable.</p> : null}
      <Button type="button" variant="secondary" disabled={!drivePicker.available || busy} onClick={() => void pick()}>
        Select in Google Drive
      </Button>
      {files.map((file) => <p key={file.id} className="source-selection">{file.name}</p>)}
      {files.length === 0 ? null : (
        <p className="source-selection" role="status">
          {busy ? "선택한 Drive 파일을 연결하는 중입니다." : `${files.length}개 파일이 선택되었습니다.`}
        </p>
      )}
      {files.length === 0 || error === null ? null : (
        <Button type="button" disabled={busy} onClick={() => void mount()}>
          Retry tracking selected files
        </Button>
      )}
      {error === null ? null : <p className="source-error" role="alert">{error}</p>}
    </div>
  );
}

function GitHubCompletion({
  sourceApi,
  connectionId,
  riskWorkspaceId,
  onComplete,
}: {
  sourceApi: SourceApiClient;
  connectionId: string;
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
    void sourceApi.githubRepositories(connectionId).then((items) => {
      if (!active) return;
      setRepositories(items);
      const first = items[0];
      if (first !== undefined) {
        setSelectedId(String(first.id));
        setBranch(first.defaultBranch);
      }
    }).catch(() => active && setError("설치에서 접근 가능한 repository를 불러오지 못했습니다.")).finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [connectionId, sourceApi]);

  const repository = repositories.find((item) => String(item.id) === selectedId) ?? null;

  async function mount(): Promise<void> {
    if (repository === null || !branch.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await sourceApi.createGithubMount(connectionId, riskWorkspaceId, repository, branch.trim());
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
      <h2>Select repository and branch</h2>
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
