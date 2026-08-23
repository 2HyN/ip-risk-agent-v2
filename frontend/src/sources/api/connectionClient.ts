import type { ApiClient } from "../../shared/api/client.js";

export type SourceType = "GOOGLE_DRIVE" | "GITHUB" | "LOCAL";

export interface StartConnectionResponse {
  authorizeUrl: string;
  state: string;
}

export interface MountCreationResponse {
  serverMountId: string;
  sourceWorkspaceId: string;
  /**
   * 붙인 직후 폴더에서 실제로 찾은 파일 수. **0 도 답이다** — 이 값이 없으면
   * 화면에서 "빈 폴더" 와 "못 읽는 폴더" 가 똑같이 아무것도 아닌 것으로 보인다
   * (결함 40). Drive 마운트에만 있다.
   */
  trackedFileCount: number | null;
  truncated: boolean;
}

export interface GitHubRepository {
  id: number;
  fullName: string;
  owner: string;
  name: string;
  private: boolean;
  defaultBranch: string;
}

export interface OriginalSourceResponse {
  original_source_type: "PROVIDER_URL" | "LOCAL_DEVICE";
  provider_url: string | null;
  device_id: string | null;
  source_artifact_id: string | null;
  metadata_safe: Record<string, unknown>;
}

/**
 * D1 — 화면이 알아야 할 것은 **어디로 공유하는가** 하나뿐이다.
 *
 * Picker 설정을 대신한다. Picker 는 브라우저 API 키를 내려보내야 했는데, 공유
 * 주소는 알아도 접근이 생기지 않는다 — 접근은 사용자가 폴더를 공유해야 생긴다.
 */
export interface DriveSharingRuntimeConfig {
  enabled: boolean;
  sharingAddress: string | null;
}

interface StartConnectionApiResponse {
  authorize_url: string;
  state: string;
}

interface MountCreationApiResponse {
  server_mount_id: string;
  source_workspace_id: string;
  tracked_file_count?: number | null;
  truncated?: boolean;
}

interface GitHubRepositoriesApiResponse {
  repositories: Array<{
    id: number;
    full_name: string;
    owner: string;
    name: string;
    private: boolean;
    default_branch: string;
  }>;
}

export class SourceApiClient {
  constructor(private readonly client: ApiClient) {}

  async startGithubConnection(riskWorkspaceId: string): Promise<StartConnectionResponse> {
    return this.start(
      "/api/v1/source-connections/github/install/start",
      riskWorkspaceId,
    );
  }

  /**
   * 공유받은 **폴더 하나**를 붙인다 — D1.
   *
   * 승인 화면도 Picker 도 없다. 사용자가 폴더를 서비스 계정에 공유하고 그 주소를
   * 넣으면 끝이다. 서버가 폴더인지 확인하고 몇 개를 찾았는지 함께 돌려준다.
   */
  async mountSharedDriveFolder(
    riskWorkspaceId: string,
    folderReference: string,
  ): Promise<MountCreationResponse> {
    const response = await this.client.request<MountCreationApiResponse>(
      "/api/v1/source-connections/google-drive/folders",
      {
        method: "POST",
        body: JSON.stringify({
          risk_workspace_id: riskWorkspaceId,
          folder_id: folderReference,
        }),
      },
    );
    return mapMount(response);
  }


  // `untrackDriveArtifact` 는 없앴다.
  //
  // 폴더를 보는 지금 "이 파일만 추적 해제" 는 성립하지 않는다 — 범위에서 뺄 방법이
  // 없고, Risk 만 닫아 두면 그 파일의 다음 변경에 되살아난다. 추적을 끊는 방법은
  // 하나뿐이다: 폴더 밖으로 옮긴다.

  async githubRepositories(connectionId: string): Promise<GitHubRepository[]> {
    return this.mapRepositories(
      `/api/v1/source-connections/${encodeURIComponent(connectionId)}/github/repositories`,
    );
  }

  /**
   * 이미 붙어 있는 mount 를 통해 같은 설치의 저장소 목록을 본다.
   *
   * 저장소를 하나 붙이고 나면 화면에 남는 것은 mount 뿐이다. 연결 식별자를 화면에
   * 두면 같은 계정의 여러 workspace 경계가 흐려지므로 mount 로 되찾는다.
   */
  async githubRepositoriesForMount(mountId: string): Promise<GitHubRepository[]> {
    return this.mapRepositories(
      `/api/v1/source-mounts/${encodeURIComponent(mountId)}/github/repositories`,
    );
  }

  private async mapRepositories(path: string): Promise<GitHubRepository[]> {
    const response = await this.client.request<GitHubRepositoriesApiResponse>(path);
    return response.repositories.map((repository) => ({
      id: repository.id,
      fullName: repository.full_name,
      owner: repository.owner,
      name: repository.name,
      private: repository.private,
      defaultBranch: repository.default_branch,
    }));
  }

  async createGithubMount(
    connectionId: string,
    riskWorkspaceId: string,
    repository: GitHubRepository,
    trackedBranch: string,
  ): Promise<MountCreationResponse> {
    return this.mountGithubRepository(
      `/api/v1/source-connections/${encodeURIComponent(connectionId)}/github/mounts`,
      riskWorkspaceId,
      repository,
      trackedBranch,
    );
  }

  /** 같은 연결에 저장소를 **더** 붙인다. GitHub 설치 화면을 거치지 않는다. */
  async createGithubMountForMount(
    mountId: string,
    riskWorkspaceId: string,
    repository: GitHubRepository,
    trackedBranch: string,
  ): Promise<MountCreationResponse> {
    return this.mountGithubRepository(
      `/api/v1/source-mounts/${encodeURIComponent(mountId)}/github/mounts`,
      riskWorkspaceId,
      repository,
      trackedBranch,
    );
  }

  private async mountGithubRepository(
    path: string,
    riskWorkspaceId: string,
    repository: GitHubRepository,
    trackedBranch: string,
  ): Promise<MountCreationResponse> {
    const response = await this.client.request<MountCreationApiResponse>(
      path,
      {
        method: "POST",
        body: JSON.stringify({
          risk_workspace_id: riskWorkspaceId,
          owner: repository.owner,
          repo: repository.name,
          tracked_branch: trackedBranch,
          include_patterns: [],
          exclude_patterns: [],
        }),
      },
    );
    return mapMount(response);
  }

  async issueDesktopEnrollmentChallenge(): Promise<string> {
    const response = await this.client.request<{ challenge: string }>(
      "/api/v1/desktop/enrollment-challenges",
      { method: "POST" },
    );
    return response.challenge;
  }

  async revokeDesktopDevice(deviceId: string): Promise<void> {
    await this.client.request<void>(
      `/api/v1/desktop/devices/${encodeURIComponent(deviceId)}/revoke`,
      { method: "POST" },
    );
  }

  async driveSharingRuntimeConfig(): Promise<DriveSharingRuntimeConfig> {
    const response = await this.client.request<{
      drive_sharing: {
        enabled: boolean;
        sharing_address: string | null;
      };
    }>("/api/v1/runtime-config");
    return {
      enabled: response.drive_sharing.enabled,
      sharingAddress: response.drive_sharing.sharing_address,
    };
  }

  openOriginal(riskWorkspaceId: string, artifactId: string) {
    return this.client.request<OriginalSourceResponse>(
      `/api/v1/workspaces/${encodeURIComponent(riskWorkspaceId)}/artifacts/${encodeURIComponent(artifactId)}/open-original`,
      { method: "POST" },
    );
  }

  private async start(path: string, riskWorkspaceId: string) {
    const response = await this.client.request<StartConnectionApiResponse>(path, {
      method: "POST",
      body: JSON.stringify({ risk_workspace_id: riskWorkspaceId }),
    });
    return { authorizeUrl: response.authorize_url, state: response.state };
  }
}

function mapMount(response: MountCreationApiResponse): MountCreationResponse {
  return {
    serverMountId: response.server_mount_id,
    sourceWorkspaceId: response.source_workspace_id,
    trackedFileCount: response.tracked_file_count ?? null,
    truncated: response.truncated ?? false,
  };
}
