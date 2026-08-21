export type ApiFailurePayload = {
  code?: string;
  message?: string;
  detail?: string;
  details?: Array<Record<string, unknown>>;
};

export class ApiFailure extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, payload: ApiFailurePayload = {}) {
    super(payload.message ?? payload.detail ?? "The request could not be completed.");
    this.name = "ApiFailure";
    this.status = status;
    this.code = payload.code ?? "REQUEST_FAILED";
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
