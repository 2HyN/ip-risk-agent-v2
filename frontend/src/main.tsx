import { StrictMode, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { ControlPlaneRoutes } from "./app/control-plane-app";
import { SessionProvider, useSession } from "./auth/session";
import { SourcePanel } from "./sources/SourcePanel";
import { SourceApiClient } from "./sources/api/connectionClient";
import { createOpenOriginalHandler } from "./sources/openOriginal";
import { detectPlatformAdapter } from "./sources/platform/PlatformAdapter";

function ProductRoutes() {
  const { api } = useSession();
  const platform = useMemo(() => detectPlatformAdapter(), []);
  if (
    platform.platform === "desktop" &&
    window.location.hash === "" &&
    /^\/w\/[^/]+\/sources$/u.test(window.location.pathname)
  ) {
    window.history.replaceState(
      null,
      "",
      `/app#${window.location.pathname}${window.location.search}`,
    );
  }
  const sourceApi = useMemo(() => new SourceApiClient(api.client), [api]);
  const openOriginal = useMemo(
    () => createOpenOriginalHandler(sourceApi, platform),
    [platform, sourceApi],
  );
  return (
    <ControlPlaneRoutes
      router={platform.platform === "desktop" ? "hash" : "browser"}
      integration={{
        sourcePanel: <SourcePanel platform={platform} />,
        openOriginal,
      }}
    />
  );
}

const root = document.getElementById("root");
if (root === null) throw new Error("Application root element is missing");
createRoot(root).render(
  <StrictMode>
    <SessionProvider>
      <ProductRoutes />
    </SessionProvider>
  </StrictMode>,
);
