/**
 * 연결 이후 단계 — 무엇을 감시할지 고르고, 무엇이 붙어 있는지 보여준다.
 *
 * 연결(Connection)과 감시 대상(Mount)은 다르다. OAuth/App 설치가 끝나면
 * Connection 만 생긴 상태이고, 이때는 아직 아무것도 감시하지 않는다. 저장소나
 * 폴더를 골라 Mount 를 만들어야 파이프라인이 돌기 시작한다.
 *
 * 목록은 **Control** 이 canonical 이다(`/workspaces/{id}/mounts`). Source Plane
 * 의 응답을 화면이 그대로 믿으면 provider 쪽 상태와 Control 의 기록이 갈릴 때
 * 사용자에게 거짓을 보여주게 된다.
 */

/** 전역 `fetch` 를 필드에 담아 메서드로 부르면 수신자가 어긋나 TypeError 가
 * 난다. 요청이 나가지도 않으므로 어디에도 흔적이 남지 않는다. 감싸서 쓴다. */
export type FetchLike = typeof fetch;

export type MountStatus =
  | "ACTIVE"
  | "SOURCE_OFFLINE"
  | "DISABLED"
  | "REVOKED"
  | string;

export type Mount = {
  id: string;
  riskWorkspaceId: string;
  sourceWorkspaceId: string;
  alias: string;
  sourceConnectionId: string;
  status: MountStatus;
  createdAt: string;
};

export type GithubRepository = {
  id: number;
  fullName: string;
  owner: string;
  name: string;
  private: boolean;
  defaultBranch: string;
};

type MountApiResponse = {
  id: string;
  risk_workspace_id: string;
  source_workspace_id: string;
  alias: string;
  source_connection_id: string;
  status: MountStatus;
  created_at: string;
};

type PageApiResponse<T> = { items: T[]; next_cursor: string | null };

type RepositoriesApiResponse = {
  repositories: Array<{
    id: number;
    full_name: string;
    owner: string;
    name: string;
    private: boolean;
    default_branch: string;
  }>;
};

export interface SourcesApi {
  listMounts(riskWorkspaceId: string): Promise<Mount[]>;
  listGithubRepositories(connectionId: string): Promise<GithubRepository[]>;
  createGithubMount(input: {
    connectionId: string;
    riskWorkspaceId: string;
    owner: string;
    repo: string;
  }): Promise<{ mountId: string }>;
}

export class HttpSourcesApi implements SourcesApi {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike = (...args) => fetch(...args)
  ) {}

  async listMounts(riskWorkspaceId: string): Promise<Mount[]> {
    const page = await this.request<PageApiResponse<MountApiResponse>>(
      `/api/v1/workspaces/${encodeURIComponent(riskWorkspaceId)}/mounts`
    );
    return page.items.map((item) => ({
      id: item.id,
      riskWorkspaceId: item.risk_workspace_id,
      sourceWorkspaceId: item.source_workspace_id,
      alias: item.alias,
      sourceConnectionId: item.source_connection_id,
      status: item.status,
      createdAt: item.created_at,
    }));
  }

  async listGithubRepositories(connectionId: string): Promise<GithubRepository[]> {
    const data = await this.request<RepositoriesApiResponse>(
      `/api/v1/source-connections/${encodeURIComponent(connectionId)}/github/repositories`
    );
    return data.repositories.map((r) => ({
      id: r.id,
      fullName: r.full_name,
      owner: r.owner,
      name: r.name,
      private: r.private,
      defaultBranch: r.default_branch,
    }));
  }

  async createGithubMount(input: {
    connectionId: string;
    riskWorkspaceId: string;
    owner: string;
    repo: string;
  }): Promise<{ mountId: string }> {
    const data = await this.request<{ server_mount_id: string }>(
      `/api/v1/source-connections/${encodeURIComponent(input.connectionId)}/github/mounts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // tracked_branch 는 보내지 않는다. 서버가 저장소의 기본 브랜치를
        // 조회해 채운다. 화면이 추측해 보내면 둘이 어긋날 수 있다.
        body: JSON.stringify({
          risk_workspace_id: input.riskWorkspaceId,
          owner: input.owner,
          repo: input.repo,
        }),
      }
    );
    return { mountId: data.server_mount_id };
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);
    if (!response.ok) {
      throw new Error(`request failed at ${path}: ${response.status}`);
    }
    return (await response.json()) as T;
  }
}
