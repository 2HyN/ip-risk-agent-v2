export interface EnrollmentResult {
  deviceCredential: string;
}

interface EnrollmentApiResponse {
  device_credential: string;
}

export class DeviceEnrollmentClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async exchange(
    challenge: string,
    deviceId: string,
    deviceLabel: string,
  ): Promise<EnrollmentResult> {
    const response = await this.fetchImpl(`${this.baseUrl}/desktop/devices/enroll`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        challenge,
        device_id: deviceId,
        device_label: deviceLabel,
      }),
    });
    if (!response.ok) {
      throw new Error(`desktop enrollment failed with status ${response.status}`);
    }
    const body = (await response.json()) as EnrollmentApiResponse;
    if (typeof body.device_credential !== "string" || body.device_credential.length < 32) {
      throw new Error("desktop enrollment returned an invalid credential");
    }
    return { deviceCredential: body.device_credential };
  }
}
