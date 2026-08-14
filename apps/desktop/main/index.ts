import type {
  AnalysisArtifact,
  AnalysisResult,
  SourceChange,
  SourceSnapshot,
} from "@iprisk/contracts";

export type DesktopContractImportProof = {
  change: SourceChange;
  snapshot: SourceSnapshot;
  artifact: AnalysisArtifact;
  result: AnalysisResult;
};

