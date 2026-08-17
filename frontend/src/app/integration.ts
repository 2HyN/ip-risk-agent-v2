import type { ReactNode } from "react";

export type OpenOriginalRequest = {
  workspaceId: string;
  artifactId: string;
  action: "SOURCE_OPEN_ORIGINAL";
  sourceType: "GOOGLE_DRIVE" | "GITHUB" | "LOCAL" | null;
};

export type ControlPlaneIntegration = {
  sourceNavigation?: ReactNode;
  sourcePanel?: ReactNode;
  openOriginal?: (request: OpenOriginalRequest) => void | Promise<void>;
};
