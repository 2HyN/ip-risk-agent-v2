/**
 * watcher.ts가 만든 LocalChangeEvent를 실제로 /desktop/staging,
 * /desktop/events HTTP 엔드포인트로 전달한다 — Phase D에서 watcher와
 * 라우터를 각각 만들어놓고 이 둘을 잇는 배선이 빠져있던 부분을 메운다.
 *
 * HttpClient를 포트로 분리해서, 진짜 fetch 없이도(FakeHttpClient) 지금
 * 바로 테스트할 수 있다.
 */

import { readFileSync } from "node:fs";

import type { LocalChangeEvent, LocalChangeType } from "../watcher/watcher.js";

export interface HttpClient {
  postJson(path: string, body: unknown): Promise<unknown>;
}

export interface DeviceCredentialProvider {
  getCredential(): Promise<string | null>;
}

export class FetchHttpClient implements HttpClient {
  constructor(
    private readonly baseUrl: string,
    private readonly credentials: DeviceCredentialProvider,
    private readonly fetchImpl: typeof fetch = fetch,
    private readonly delay: (milliseconds: number) => Promise<void> = (milliseconds) =>
      new Promise((resolve) => setTimeout(resolve, milliseconds)),
  ) {}

  async postJson(path: string, body: unknown): Promise<unknown> {
    const credential = await this.credentials.getCredential();
    if (credential === null) throw new Error("desktop enrollment is required");
    for (let attempt = 0; attempt < 3; attempt += 1) {
      let response: Response;
      try {
        response = await this.fetchImpl(`${this.baseUrl}${path}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            Authorization: `Bearer ${credential}`,
          },
          body: JSON.stringify(body),
        });
      } catch (reason) {
        if (attempt === 2) throw reason;
        await this.delay(100 * 2 ** attempt);
        continue;
      }
      if (response.ok) return response.json();
      if (response.status !== 429 && response.status < 500) {
        throw new Error(`request to ${path} failed with status ${response.status}`);
      }
      if (attempt === 2) {
        throw new Error(`request to ${path} failed after retries with status ${response.status}`);
      }
      await this.delay(100 * 2 ** attempt);
    }
    throw new Error(`request to ${path} failed`);
  }
}

export interface DesktopEventReporterConfig {
  riskWorkspaceId: string;
  mountId: string;
  sourceWorkspaceId: string;
  deviceId: string;
}

interface StagingUploadResponse {
  object_name: string;
}

export class DesktopEventReporter {
  constructor(
    private readonly http: HttpClient,
    private readonly config: DesktopEventReporterConfig
  ) {}

  async report(event: LocalChangeEvent): Promise<void> {
    if (event.changeType === "DELETE") {
      await this.postEvent(event.relativePath, "DELETE", undefined, undefined, undefined);
      return;
    }

    let content: string;
    try {
      content = readFileSync(event.absolutePath, "utf-8");
    } catch {
      // 파일이 이미 사라졌거나 읽을 수 없음 -> 조용히 무시.
      // 다음 watcher 이벤트(대개 뒤이은 DELETE)가 상태를 바로잡는다.
      return;
    }

    const stagingResponse = (await this.http.postJson("/desktop/staging", {
      mount_id: this.config.mountId,
      content,
    })) as StagingUploadResponse;

    await this.postEvent(
      event.relativePath,
      event.changeType,
      stagingResponse.object_name,
      event.changeType === "MOVE" ? event.previousRelativePath : undefined,
      event.contentHash
    );
  }

  private async postEvent(
    relativePath: string,
    changeType: LocalChangeType,
    stagingObjectName: string | undefined,
    previousRelativePath: string | undefined,
    revision: string | undefined
  ): Promise<void> {
    await this.http.postJson("/desktop/events", {
      risk_workspace_id: this.config.riskWorkspaceId,
      mount_id: this.config.mountId,
      source_workspace_id: this.config.sourceWorkspaceId,
      device_id: this.config.deviceId,
      relative_path: relativePath,
      change_type: changeType,
      staging_object_name: stagingObjectName,
      previous_relative_path: previousRelativePath,
      // Local 에는 provider 판본이 없다. 내용 해시가 그 자리다.
      revision,
    });
  }
}
