import { createContext, useContext } from "react";
import type { ControlPlaneIntegration } from "./integration";

export const IntegrationContext = createContext<ControlPlaneIntegration>({});
export function useIntegration(): ControlPlaneIntegration {
  return useContext(IntegrationContext);
}
