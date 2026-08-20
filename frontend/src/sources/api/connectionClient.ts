/**
 * AddSourceChooser의 Drive/GitHub 버튼이 실제로 부를 API. 백엔드의
 * OAuth/App 설치 시작 라우터(/source-connections/google-drive/start,
 * /source-connections/github/install/start)를 그대로 호출한다.
 */

export interface StartConnectionResponse {
  authorizeUrl: string;
  state: string;
}

export interface ConnectionApiClient {
  startDriveConnection(riskWorkspaceId: string): Promise<StartConnectionResponse>;
  startGithubConnection(riskWorkspaceId: string): Promise<StartConnectionResponse>;
}

interface StartConnectionApiResponse {
  authorize_url: string;
  state: string;
}

export type FetchLike = typeof fetch;

export class HttpConnectionApiClient implements ConnectionApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike = fetch
  ) {}

  async startDriveConnection(riskWorkspaceId: string): Promise<StartConnectionResponse> {
    return this.post("/api/v1/source-connections/google-drive/start", riskWorkspaceId);
  }

  async startGithubConnection(riskWorkspaceId: string): Promise<StartConnectionResponse> {
    return this.post("/api/v1/source-connections/github/install/start", riskWorkspaceId);
  }

  private async post(path: string, riskWorkspaceId: string): Promise<StartConnectionResponse> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ risk_workspace_id: riskWorkspaceId }),
    });
    if (!response.ok) {
      throw new Error(`failed to start connection at ${path}: ${response.status}`);
    }
    const data = (await response.json()) as StartConnectionApiResponse;
    return { authorizeUrl: data.authorize_url, state: data.state };
  }
}
