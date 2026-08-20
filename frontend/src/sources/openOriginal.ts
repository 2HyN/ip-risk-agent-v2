import type { OpenOriginalRequest } from "../app/integration.js";
import type { SourceApiClient } from "./api/connectionClient.js";
import type { PlatformAdapter } from "./platform/PlatformAdapter.js";

export function createOpenOriginalHandler(
  sourceApi: SourceApiClient,
  platform: PlatformAdapter,
  openProviderUrl: (url: string) => void = (url) => {
    window.open(url, "_blank", "noopener,noreferrer");
  },
) {
  return async (request: OpenOriginalRequest): Promise<void> => {
    const locator = await sourceApi.openOriginal(request.workspaceId, request.artifactId);
    if (locator.original_source_type === "PROVIDER_URL") {
      const url = validateProviderUrl(locator.provider_url, request.sourceType);
      openProviderUrl(url);
      return;
    }
    if (
      request.sourceType !== "LOCAL" ||
      platform.platform !== "desktop" ||
      locator.device_id === null ||
      locator.source_artifact_id === null
    ) {
      throw new Error("The original is only available on its enrolled desktop.");
    }
    await platform.openLocalOriginal(locator.device_id, locator.source_artifact_id);
  };
}

function validateProviderUrl(
  raw: string | null,
  sourceType: OpenOriginalRequest["sourceType"],
): string {
  if (raw === null) throw new Error("Provider did not return an original URL.");
  const parsed = new URL(raw);
  const expectedHost = sourceType === "GOOGLE_DRIVE"
    ? "drive.google.com"
    : sourceType === "GITHUB"
      ? "github.com"
      : null;
  if (
    expectedHost === null ||
    parsed.protocol !== "https:" ||
    parsed.hostname !== expectedHost ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    (parsed.port !== "" && parsed.port !== "443")
  ) {
    throw new Error("Provider returned an untrusted original URL.");
  }
  return parsed.toString();
}
