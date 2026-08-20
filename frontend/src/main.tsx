/**
 * 웹 진입점.
 *
 * Control Plane UI 에 Source Plane 화면을 public integration prop 으로 주입한다.
 * 두 Plane 은 서로의 파일을 import 하지 않는다 — 연결은 이 파일에서만 일어난다
 * (AGENT_1_DELIVERY 8, Master Spec 42).
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ControlPlaneApp } from "./app/control-plane-app";
import type { OpenOriginalRequest } from "./app/integration";
import { SourcePanel } from "./sources/SourcePanel";

/**
 * Open Original 은 아직 백엔드 resolver 가 없다.
 *
 * 콜백을 아예 주지 않으면 버튼이 이유와 함께 disabled 로 fail closed 되므로,
 * 여기서 임의로 열어주는 대신 그 상태를 그대로 둔다. resolver 가 준비되면
 * 이 자리에 `facade.get_original_source_request` 를 호출하는 구현을 넣는다.
 */
const openOriginal: ((request: OpenOriginalRequest) => void) | undefined =
  undefined;

const root = document.getElementById("root");
if (root === null) throw new Error("Application root element is missing");

createRoot(root).render(
  <StrictMode>
    <ControlPlaneApp
      router="browser"
      integration={{
        sourcePanel: <SourcePanel />,
        ...(openOriginal ? { openOriginal } : {}),
      }}
    />
  </StrictMode>,
);
