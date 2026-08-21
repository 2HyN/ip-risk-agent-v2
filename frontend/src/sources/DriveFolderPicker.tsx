/**
 * Drive 연결 직후 무엇을 감시할지 고르는 단계.
 *
 * `drive.file` 스코프에서는 서버가 사용자의 Drive 를 마음대로 뒤질 수 없다 —
 * **사용자가 Google Picker 로 고른 파일에만** 앱 접근이 열린다. 그래서 이
 * 단계는 브라우저에서 Google 의 Picker UI 를 띄우는 것 외의 대안이 없다.
 * 서버 목록 조회로 대체하려는 시도는 스코프 상승(전체 Drive 읽기)을 뜻하므로
 * 하지 않는다.
 *
 * 토큰은 서버가 쥔다. 브라우저는 picker-session 으로 **짧은 수명의 access
 * token 만** 받아 Picker 에 넘기고, refresh token 은 서버 vault 밖으로 나오지
 * 않는다.
 */

import { useState } from "react";

import type { SourcesApi } from "./api/sourcesClient.js";

const PICKER_SCRIPT_URL = "https://apis.google.com/js/api.js";

/** 선택 결과. null 은 사용자가 창을 닫은 것 — 오류가 아니다. */
export type PickFiles = (session: {
  accessToken: string;
  apiKey: string;
  appId: string | null;
}) => Promise<string[] | null>;

declare global {
  interface Window {
    gapi?: {
      load: (name: string, callback: () => void) => void;
    };
    google?: {
      picker: Record<string, any>;
    };
  }
}

let pickerScriptPromise: Promise<void> | null = null;

function loadPickerScript(): Promise<void> {
  // 같은 페이지에서 여러 번 열어도 스크립트는 한 번만 넣는다.
  if (pickerScriptPromise) return pickerScriptPromise;
  pickerScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PICKER_SCRIPT_URL;
    script.async = true;
    script.onload = () => {
      if (!window.gapi) {
        reject(new Error("picker script loaded but gapi is missing"));
        return;
      }
      window.gapi.load("picker", () => resolve());
    };
    script.onerror = () => {
      // 실패한 약속을 캐시하면 새로고침 전까지 재시도가 불가능해진다.
      pickerScriptPromise = null;
      reject(new Error("failed to load the Google Picker script"));
    };
    document.head.appendChild(script);
  });
  return pickerScriptPromise;
}

/** 실제 Google Picker 를 연다. 테스트에서는 이 구현을 통째로 대체한다. */
const openGooglePicker: PickFiles = async ({ accessToken, apiKey, appId }) => {
  await loadPickerScript();
  const picker = window.google?.picker;
  if (!picker) throw new Error("google.picker is unavailable after load");

  return new Promise<string[] | null>((resolve) => {
    // 폴더째 감시하는 것이 목적이므로 폴더 선택을 켠다. 개별 파일도
    // 고를 수 있게 문서 뷰를 함께 둔다.
    const docsView = new picker.DocsView(picker.ViewId.DOCS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(true);

    const builder = new picker.PickerBuilder()
      .setOAuthToken(accessToken)
      .setDeveloperKey(apiKey)
      .addView(docsView)
      .enableFeature(picker.Feature.MULTISELECT_ENABLED)
      .setCallback((data: { action: string; docs?: Array<{ id: string }> }) => {
        if (data.action === picker.Action.PICKED) {
          resolve((data.docs ?? []).map((doc) => doc.id));
        } else if (data.action === picker.Action.CANCEL) {
          resolve(null);
        }
      });
    // appId 는 drive.file 접근 허가를 이 앱(프로젝트)으로 귀속시킨다.
    // 없으면 고른 파일이 앱에 열리지 않아, 선택은 됐는데 수집이 막힌다.
    if (appId) builder.setAppId(appId);
    // Picker 는 Google 도메인의 iframe 에서 돈다. origin 을 명시해야 키의
    // referrer 검증이 이 페이지 기준으로 이뤄진다. 빼면 키에 referrer
    // 제한을 걸었을 때 "developer key is invalid" 로 거부된다.
    builder.setOrigin(window.location.origin);
    builder.build().setVisible(true);
  });
};

export type DriveFolderPickerProps = {
  api: SourcesApi;
  connectionId: string;
  riskWorkspaceId: string;
  onMounted: () => void;
  /** 테스트 주입용. 기본값이 실제 Google Picker 다. */
  pickFiles?: PickFiles;
};

export function DriveFolderPicker({
  api,
  connectionId,
  riskWorkspaceId,
  onMounted,
  pickFiles = openGooglePicker,
}: DriveFolderPickerProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = async () => {
    setError(null);
    setBusy(true);
    try {
      const session = await api.createDrivePickerSession(connectionId);
      if (!session.apiKey) {
        // 배포에 GOOGLE_PICKER_API_KEY 가 없다. 사용자가 고칠 수 있는 문제가
        // 아니므로 "다시 시도"라고 말하면 안 된다.
        setError(
          "이 배포에는 Google Picker API 키가 설정되지 않았습니다. " +
            "관리자가 GOOGLE_PICKER_API_KEY 를 설정해야 합니다."
        );
        return;
      }

      const fileIds = await pickFiles({
        accessToken: session.accessToken,
        apiKey: session.apiKey,
        appId: session.appId,
      });
      if (fileIds === null) return; // 사용자가 창을 닫았다. 오류가 아니다.
      if (fileIds.length === 0) return;

      await api.createDriveMount({
        connectionId,
        riskWorkspaceId,
        selectedFileIds: fileIds,
      });
      onMounted();
    } catch (cause) {
      console.error(cause);
      const reason = cause instanceof Error ? cause.message : "";
      setError(
        reason.includes("401")
          ? "Drive 접근 권한이 만료되었습니다. Google Drive 연결을 다시 시작해 주세요."
          : reason.includes("404")
            ? "이 연결을 찾을 수 없습니다. Google Drive 연결을 다시 시작해 주세요."
            : "폴더 선택을 완료하지 못했습니다."
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>감시할 폴더 선택</h2>
      <p>
        Google Drive 에서 감시할 폴더나 파일을 고릅니다. 폴더를 고르면 그
        안의 모든 파일(하위 폴더 포함)이 감시 대상이 됩니다.
      </p>
      <p>
        {/* 펼침은 연결 시점의 스냅샷이다. 이 한계를 숨기면 사용자는
            "새 파일도 자동으로 검사되겠지"라고 오해한다. */}
        연결 이후 폴더에 새로 추가된 파일은 자동으로 검사되지 않습니다. 새
        파일까지 포함하려면 폴더를 다시 선택해 주세요.
      </p>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <button type="button" onClick={() => void open()} disabled={busy}>
        {busy ? "여는 중…" : "Google Drive 에서 선택"}
      </button>
    </section>
  );
}
