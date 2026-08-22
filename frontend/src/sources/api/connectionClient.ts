import type { ApiClient } from "../../shared/api/client.js";

export type SourceType = "GOOGLE_DRIVE" | "GITHUB" | "LOCAL";

export interface StartConnectionResponse {
  authorizeUrl: string;
  state: string;
}

export interface MountCreationResponse {
  serverMountId: string;
  sourceWorkspaceId: string;
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

export interface DrivePickerRuntimeConfig {
  enabled: boolean;
  browserApiKey: string | null;
  cloudProjectNumber: string | null;
}

interface StartConnectionApiResponse {
  authorize_url: string;
  state: string;
}

interface MountCreationApiResponse {
  server_mount_id: string;
  source_workspace_id: string;
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

  async startDriveConnection(riskWorkspaceId: string): Promise<StartConnectionResponse> {
    return this.start(
      "/api/v1/source-connections/google-drive/start",
      riskWorkspaceId,
    );
  }

  async startGithubConnection(riskWorkspaceId: string): Promise<StartConnectionResponse> {
    return this.start(
      "/api/v1/source-connections/github/install/start",
      riskWorkspaceId,
    );
  }

  async createDrivePickerSession(connectionId: string): Promise<string> {
    const response = await this.client.request<{ access_token: string }>(
      `/api/v1/source-connections/${encodeURIComponent(connectionId)}/drive/picker-session`,
      { method: "POST" },
    );
    return response.access_token;
  }

  async createDrivePickerSessionForMount(mountId: string): Promise<string> {
    const response = await this.client.request<{ access_token: string }>(
      `/api/v1/source-mounts/${encodeURIComponent(mountId)}/drive/picker-session`,
      { method: "POST" },
    );
    return response.access_token;
  }

  async createDriveMount(
    connectionId: string,
    riskWorkspaceId: string,
    selectedFileIds: string[],
    displayMetadataByFile: Record<string, { name: string }> = {},
  ): Promise<MountCreationResponse> {
    const response = await this.client.request<MountCreationApiResponse>(
      `/api/v1/source-connections/${encodeURIComponent(connectionId)}/drive/mounts`,
      {
        method: "POST",
        body: JSON.stringify({
          risk_workspace_id: riskWorkspaceId,
          selected_file_ids: selectedFileIds,
          display_metadata_by_file: displayMetadataByFile,
        }),
      },
    );
    return mapMount(response);
  }

  async createAdditionalDriveMount(
    mountId: string,
    riskWorkspaceId: string,
    selectedFileIds: string[],
    displayMetadataByFile: Record<string, { name: string }> = {},
  ): Promise<MountCreationResponse> {
    const response = await this.client.request<MountCreationApiResponse>(
      `/api/v1/source-mounts/${encodeURIComponent(mountId)}/drive/mounts`,
      {
        method: "POST",
        body: JSON.stringify({
          risk_workspace_id: riskWorkspaceId,
          selected_file_ids: selectedFileIds,
          display_metadata_by_file: displayMetadataByFile,
        }),
      },
    );
    return mapMount(response);
  }

  async untrackDriveArtifact(
    mountId: string,
    riskWorkspaceId: string,
    artifactId: string,
  ): Promise<{ excluded_risk_ids: string[]; remaining_file_count: number }> {
    return this.client.request<{
      artifact_id: string;
      excluded_risk_ids: string[];
      remaining_file_count: number;
    }>(`/api/v1/source-mounts/${encodeURIComponent(mountId)}/drive/untrack`, {
      method: "POST",
      body: JSON.stringify({
        risk_workspace_id: riskWorkspaceId,
        artifact_id: artifactId,
      }),
    });
  }

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

  async drivePickerRuntimeConfig(): Promise<DrivePickerRuntimeConfig> {
    const response = await this.client.request<{
      drive_picker: {
        enabled: boolean;
        browser_api_key: string | null;
        cloud_project_number: string | null;
      };
    }>("/api/v1/runtime-config");
    return {
      enabled: response.drive_picker.enabled,
      browserApiKey: response.drive_picker.browser_api_key,
      cloudProjectNumber: response.drive_picker.cloud_project_number,
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
  };
}
