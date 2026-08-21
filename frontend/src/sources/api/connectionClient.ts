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
    // 전역 `fetch` 를 그대로 담으면 안 된다. `this.fetchImpl(...)` 로 부르는
    // 순간 수신자가 이 인스턴스가 되고, 브라우저는 `fetch` 가 Window 에서
    // 불리지 않았다며 TypeError 를 던진다. 요청이 아예 나가지 않아 네트워크
    // 탭에는 아무것도 남지 않고 화면에는 "연결 실패"로만 보인다.
    // 감싸서 전역 수신자로 부른다.
    private readonly fetchImpl: FetchLike = (...args) => fetch(...args)
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
      // 이 라우트는 Control 의 VWS Role 검사를 거친다. 세션 쿠키를 함께
      // 보내지 않으면 401 로 막히고, 화면에는 "연결 실패"로만 보인다.
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error(`failed to start connection at ${path}: ${response.status}`);
    }
    const data = (await response.json()) as StartConnectionApiResponse;
    return { authorizeUrl: data.authorize_url, state: data.state };
  }
}
