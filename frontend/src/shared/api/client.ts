/**
 * `detail` 은 문자열일 수도, 구조를 가진 객체일 수도 있다.
 *
 * FastAPI 의 `HTTPException(detail=...)` 이 둘 다 허용하고, 사용자가 다음에 무엇을
 * 해야 하는지를 담아야 하는 실패(예: Drive 폴더가 아직 공유되지 않았다)는 코드와
 * 문구를 함께 들고 온다.
 */
export type ApiFailureDetail = string | { code?: string; message?: string; [key: string]: unknown };

export type ApiFailurePayload = {
  code?: string;
  message?: string;
  detail?: ApiFailureDetail;
  details?: Array<Record<string, unknown>>;
};

export class ApiFailure extends Error {
  readonly status: number;
  readonly code: string;
  /** 서버가 준 그대로. 무엇을 해야 하는지를 담은 실패는 여기에만 들어 있다. */
  readonly detail: ApiFailureDetail | null;

  constructor(status: number, payload: ApiFailurePayload = {}) {
    const detail = payload.detail ?? null;
    const structured = typeof detail === "object" && detail !== null ? detail : null;
    super(
      payload.message
      ?? structured?.message
      ?? (typeof detail === "string" ? detail : undefined)
      ?? "The request could not be completed.",
    );
    this.name = "ApiFailure";
    this.status = status;
    this.code = payload.code ?? structured?.code ?? "REQUEST_FAILED";
    this.detail = detail;
  }
}

export class ApiClient {
  private csrfToken: string | null = null;

  constructor(private readonly baseUrl = "") {}

  setCsrfToken(token: string | null): void {
    this.csrfToken = token;
  }

  url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const method = (init.method ?? "GET").toUpperCase();
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (
      !["GET", "HEAD", "OPTIONS"].includes(method) &&
      this.csrfToken !== null
    ) {
      headers.set("X-CSRF-Token", this.csrfToken);
    }
    const response = await fetch(this.url(path), {
      ...init,
      headers,
      credentials: "include",
    });
    if (!response.ok) {
      let payload: ApiFailurePayload = {};
      try {
        payload = (await response.json()) as ApiFailurePayload;
      } catch {
        // The safe server status is still useful when a proxy has no JSON body.
      }
      throw new ApiFailure(response.status, payload);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
}

export function queryString(
  values: Record<string, string | number | boolean | null | undefined>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "")
      query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded === "" ? "" : `?${encoded}`;
}
