import { useEffect, useState } from "react";

import { Button, Field, Textarea } from "../shared/ui/index.js";
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
  const [includeText, setIncludeText] = useState("");
  const [excludeText, setExcludeText] = useState("node_modules/**\n.git/**");
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
      const mount = await platform.connectLocalMount({
        selectionId: selection.selectionId,
        riskWorkspaceId,
        includePatterns: patterns(includeText),
        excludePatterns: patterns(excludeText),
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
          <Field label="Include patterns" hint="한 줄에 하나 · 비워두면 허용 확장자 전체">
            <Textarea
              rows={3}
              value={includeText}
              onChange={(event) => setIncludeText(event.target.value)}
            />
          </Field>
          <Field label="Exclude patterns" hint="한 줄에 하나">
            <Textarea
              rows={3}
              value={excludeText}
              onChange={(event) => setExcludeText(event.target.value)}
            />
          </Field>
          <Button type="button" disabled={busy} onClick={() => void connect()}>
            {busy ? "Connecting…" : "Connect selected folder"}
          </Button>
        </div>
      )}
      {error === null ? null : <p className="source-error" role="alert">{error}</p>}
    </div>
  );
}

function patterns(value: string): string[] {
  return value
    .split(/\r?\n/u)
    .map((item) => item.trim())
    .filter(Boolean);
}
