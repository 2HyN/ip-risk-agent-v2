import { useEffect, useState } from "react";

import { Button } from "../shared/ui/index.js";
import type {
  DesktopConnectionStatus,
  LocalMountConnection,
  PlatformAdapter,
} from "./platform/PlatformAdapter.js";

export interface ConnectLocalSourceProps {
  platform: PlatformAdapter;
  riskWorkspaceId: string;
  issueEnrollmentChallenge: () => Promise<string>;
  revokeDesktopDevice: (deviceId: string) => Promise<void>;
  onConnected: (mount: LocalMountConnection) => void;
}

export function ConnectLocalSource({
  platform,
  riskWorkspaceId,
  issueEnrollmentChallenge,
  revokeDesktopDevice,
  onConnected,
}: ConnectLocalSourceProps) {
  const [device, setDevice] = useState<DesktopConnectionStatus | null>(null);
  const [selection, setSelection] = useState<{
    selectionId: string;
    displayName: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (platform.platform === "desktop") {
      void platform.getDesktopConnectionStatus().then(setDevice).catch(() => {
        setError("Desktop connection status를 확인하지 못했습니다.");
      });
    }
  }, [platform]);

  async function enroll(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const challenge = await issueEnrollmentChallenge();
      setDevice(await platform.enrollDesktopDevice(challenge));
    } catch {
      setError("이 Desktop을 현재 로그인 세션에 등록하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function pick(): Promise<void> {
    setError(null);
    try {
      setSelection(await platform.chooseLocalDirectory());
    } catch {
      setError("폴더 선택을 완료하지 못했습니다.");
    }
  }

  async function revoke(): Promise<void> {
    if (device === null || !device.deviceId) return;
    setBusy(true);
    setError(null);
    try {
      await revokeDesktopDevice(device.deviceId);
      setDevice(await platform.clearDesktopCredential());
      setSelection(null);
    } catch {
      setError("이 Desktop의 자격증명을 폐기하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function connect(): Promise<void> {
    if (selection === null || device?.enrolled !== true) return;
    setBusy(true);
    setError(null);
    try {
      // 패턴 입력은 화면에서 뺐다 — 마운트는 폴더 단위이고, 추적할 것을 고르는
      // 방법은 폴더에 무엇을 넣는가다. 빌드 산출물만 기본으로 거른다.
      const mount = await platform.connectLocalMount({
        selectionId: selection.selectionId,
        riskWorkspaceId,
        includePatterns: [],
        excludePatterns: ["node_modules/**", ".git/**"],
      });
      setSelection(null);
      setDevice(await platform.getDesktopConnectionStatus());
      onConnected(mount);
    } catch {
      setError("Local mount를 등록하거나 watcher를 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  if (platform.platform !== "desktop") {
    return <p>Local Folder는 Desktop 앱에서만 연결할 수 있습니다.</p>;
  }

  return (
    <div className="source-local-flow">
      <h3>Local Folder</h3>
      <p>
        절대 경로는 Desktop main process 밖으로 전달되지 않습니다. 서버에는
        canonical mount ID와 상대 경로만 전송됩니다.
      </p>
      {device?.enrolled === true ? (
        <div className="source-selection">
          <p className="source-success">
            Desktop enrolled · {device.mountCount} local mount(s)
          </p>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => void enroll()}>
            Rotate desktop credential
          </Button>
          <Button type="button" variant="danger" disabled={busy} onClick={() => void revoke()}>
            Revoke desktop
          </Button>
        </div>
      ) : (
        <Button type="button" disabled={busy} onClick={() => void enroll()}>
          {busy ? "Enrolling…" : "Enroll this desktop"}
        </Button>
      )}
      <Button
        type="button"
        variant="secondary"
        disabled={device?.enrolled !== true || busy}
        onClick={() => void pick()}
      >
        Choose Folder
      </Button>
      {selection === null ? null : (
        <div className="source-selection">
          <strong>{selection.displayName}</strong>
          <p>
            이 폴더가 통째로 마운트됩니다 (파일 단위 선택이 아닙니다). 빌드
            산출물(node_modules, .git)은 자동으로 제외됩니다.
          </p>
          <Button type="button" disabled={busy} onClick={() => void connect()}>
            {busy ? "Connecting…" : "Connect selected folder"}
          </Button>
        </div>
      )}
      {error === null ? null : <p className="source-error" role="alert">{error}</p>}
    </div>
  );
}
