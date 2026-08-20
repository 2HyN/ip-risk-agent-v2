import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiFailure } from "../shared/api/client";

afterEach(() => vi.unstubAllGlobals());

describe("ApiClient", () => {
  it("sends credentials and CSRF only for state-changing requests", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), {
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const client = new ApiClient("https://control.example");
    client.setCsrfToken("csrf-value");
    await client.request("/read");
    await client.request("/write", { method: "POST", body: "{}" });
    const readInit = fetchMock.mock.calls[0]?.[1];
    const writeInit = fetchMock.mock.calls[1]?.[1];
    expect(new Headers(readInit?.headers).has("X-CSRF-Token")).toBe(false);
    expect(new Headers(writeInit?.headers).get("X-CSRF-Token")).toBe("csrf-value");
    expect(writeInit?.credentials).toBe("include");
  });

  it("exposes only the server safe error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "PERMISSION_DENIED", message: "Permission denied" }), { status: 403, headers: { "Content-Type": "application/json" } })));
    try {
      await new ApiClient().request("/denied");
      throw new Error("Expected request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiFailure);
      expect(error).toMatchObject({
        status: 403,
        code: "PERMISSION_DENIED",
        message: "Permission denied",
      });
    }
  });
});
