import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ControlPlaneApp } from "./app/control-plane-app";

const root = document.getElementById("root");
if (root === null) throw new Error("Application root element is missing");
createRoot(root).render(
  <StrictMode>
    <ControlPlaneApp />
  </StrictMode>,
);
