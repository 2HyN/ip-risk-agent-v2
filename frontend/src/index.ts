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

