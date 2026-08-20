/**
 * "폴더 선택 → 서버에 등록 → 로컬에서 감시 시작"의 중간 단계.
 * /desktop/devices/register, /desktop/mounts/register를 실제로 호출한다.
 * D-4/A-2에서 라우터는 만들었지만, Electron이 실제로 이걸 부르는 코드가
 * 없었던 부분을 메운다.
 */

import type { HttpClient } from "./desktop-event-reporter.js";

export interface RegisterMountParams {
  riskWorkspaceId: string;
  deviceId: string;
  includePatterns: string[];
  excludePatterns: string[];
}

export interface RegisterMountResult {
  serverMountId: string;
  sourceWorkspaceId: string;
}

export interface MountRegistrationClient {
  registerDevice(deviceId: string, deviceLabel: string): Promise<void>;
  registerMount(params: RegisterMountParams): Promise<RegisterMountResult>;
}

interface MountRegisterResponse {
  server_mount_id: string;
  source_workspace_id: string;
}

export class HttpMountRegistrationClient implements MountRegistrationClient {
  constructor(private readonly http: HttpClient) {}

  async registerDevice(deviceId: string, deviceLabel: string): Promise<void> {
    await this.http.postJson("/desktop/devices/register", {
      device_id: deviceId,
      device_label: deviceLabel,
    });
  }

  async registerMount(params: RegisterMountParams): Promise<RegisterMountResult> {
    const response = (await this.http.postJson("/desktop/mounts/register", {
      risk_workspace_id: params.riskWorkspaceId,
      device_id: params.deviceId,
      include_patterns: params.includePatterns,
      exclude_patterns: params.excludePatterns,
    })) as MountRegisterResponse;

    return {
      serverMountId: response.server_mount_id,
      sourceWorkspaceId: response.source_workspace_id,
    };
  }
}
