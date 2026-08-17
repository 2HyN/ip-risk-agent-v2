import type {
  AnalysisArtifact,
  AnalysisResult,
  SourceChange,
  SourceSnapshot,
} from "@iprisk/contracts";

export type ContractImportProof = {
  change: SourceChange;
  snapshot: SourceSnapshot;
  artifact: AnalysisArtifact;
  result: AnalysisResult;
};

export { ControlPlaneApp } from "./app/control-plane-app";
export type { ControlPlaneAppProps } from "./app/control-plane-app";
export type {
  ControlPlaneIntegration,
  OpenOriginalRequest,
} from "./app/integration";
export { ApiClient, ApiFailure } from "./shared/api/client";
export { ControlApi } from "./shared/api/control-api";
