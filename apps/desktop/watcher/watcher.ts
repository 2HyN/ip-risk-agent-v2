/**
 * Local 폴더 watcher. Agent 2 Spec 26번을 구현한다.
 *
 * MOVE 감지: chokidar를 비롯한 대부분의 파일 감시 라이브러리는 rename을
 * 직접 알려주지 않고 unlink(옛 경로)+add(새 경로)로 따로 알려준다. 그래서
 * "내용 해시가 같은 삭제+생성 쌍"을 짧은 시간 안에서 찾아 MOVE로 합치는
 * best-effort 방식을 쓴다 (완벽한 방법은 없음 — 내용이 우연히 같은 서로
 * 다른 두 파일이면 잘못 합칠 수 있음, 알려진 한계로 문서화함).
 *
 * chokidar의 atomic 옵션(에디터 저장 패턴 자동 감지, 기본 켜짐)은 우리
 * 자체 rename 감지 로직과 타이밍이 충돌해서 명시적으로 껐다 (atomic: false).
 */

import chokidar, { type FSWatcher } from "chokidar";
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { relative, sep } from "node:path";

import { DEBOUNCE_MS, MAX_FILE_BYTES, isWatchedPath } from "./filters.js";
import { isDeniedByIpriskignore, loadIpriskignorePatterns } from "./ipriskignore.js";
import { RootEscapeError, resolveWithinRoot } from "../security/path-guard.js";

export type LocalChangeType = "CREATE" | "UPDATE" | "DELETE" | "MOVE";

export interface LocalChangeEvent {
  relativePath: string;
  changeType: LocalChangeType;
  absolutePath: string;
  previousRelativePath?: string;
  /**
   * 이 판본을 가리키는 값. 내용의 SHA-256 이다.
   *
   * Local 에는 provider 가 주는 판본 번호가 없다. 내용 해시가 그 자리를 대신한다 —
   * 같은 내용이면 같은 판본이므로 앱을 다시 켜서 같은 파일을 또 올려도 **같은
   * 변경으로 수렴한다.** staging 객체 이름은 올릴 때마다 무작위로 붙으므로 그 자리를
   * 대신할 수 없다.
   *
   * 지워진 파일에는 없다. 내용이 이미 사라졌기 때문이다.
   */
  contentHash?: string;
}

export interface LocalWatcherOptions {
  debounceMs?: number;
  maxFileBytes?: number;
  moveCorrelationWindowMs?: number;
  /**
   * 폴더에 **이미 있던** 파일도 보고할 것인가.
   *
   * 감시는 준비되기 전의 `add` 를 버린다 — 앱을 다시 켤 때마다 이미 보고한 파일이
   * 전부 다시 올라오는 것을 막기 위해서다. 그런데 **처음 연결할 때는** 그 규칙
   * 때문에 아무것도 올라가지 않는다. 폴더를 붙였는데 파일이 하나도 보이지 않는
   * 상태가 그것이었다.
   *
   * GitHub 은 마운트 시점에 저장소를 훑는 별도 경로(`initial_changes`)가 있다.
   * Local 은 그 자리가 비어 있어 여기서 채운다.
   */
  emitExisting?: boolean;
}

export interface LocalWatcherHandle {
  close(): Promise<void>;
}

type RawEvent = "add" | "change" | "unlink";
type PendingChangeType = "CREATE" | "UPDATE" | "DELETE";

interface PendingEntry {
  timer: ReturnType<typeof setTimeout>;
  changeType: PendingChangeType;
  absolutePath: string;
}

interface PendingDeleteEntry {
  relativePath: string;
  absolutePath: string;
  timer: ReturnType<typeof setTimeout>;
}

const RAW_TO_CHANGE_TYPE: Record<RawEvent, PendingChangeType> = {
  add: "CREATE",
  change: "UPDATE",
  unlink: "DELETE",
};

const DEFAULT_MOVE_CORRELATION_WINDOW_MS = 2000;

function hashFileContent(absolutePath: string): string | null {
  try {
    const buffer = readFileSync(absolutePath);
    return createHash("sha256").update(buffer).digest("hex");
  } catch {
    return null;
  }
}

export async function startLocalWatcher(
  canonicalRoot: string,
  onChange: (event: LocalChangeEvent) => void,
  options: LocalWatcherOptions = {}
): Promise<LocalWatcherHandle> {
  const debounceMs = options.debounceMs ?? DEBOUNCE_MS;
  const maxFileBytes = options.maxFileBytes ?? MAX_FILE_BYTES;
  const moveCorrelationWindowMs = options.moveCorrelationWindowMs ?? DEFAULT_MOVE_CORRELATION_WINDOW_MS;
  const emitExisting = options.emitExisting ?? false;

  // Source-level .ipriskignore (Agent2 Spec §28). watcher 시작 시 한 번만
  // 로드한다 — 파일이 없으면 빈 목록(제약 없음)이 조용히 반환된다.
  const sourceIgnorePatterns = loadIpriskignorePatterns(canonicalRoot);

  const isPathAllowed = (relativePath: string): boolean =>
    isWatchedPath(relativePath) && !isDeniedByIpriskignore(relativePath, sourceIgnorePatterns);

  const pending = new Map<string, PendingEntry>();
  const contentHashCache = new Map<string, string>();
  const pendingDeletes = new Map<string, PendingDeleteEntry>();

  const emitDelete = (relativePath: string, absolutePath: string): void => {
    onChange({ relativePath, changeType: "DELETE", absolutePath });
  };

  let isReady = false;

  /**
   * 감시 뿌리 기준 상대 경로. **구분자는 항상 `/`** 다.
   *
   * Windows 에서 `path.relative` 는 `docs\design.md` 처럼 역슬래시를 준다. 서버는
   * provider 상대 경로만 받고 역슬래시를 거부하므로, 그대로 보내면 **하위 폴더에
   * 있는 파일만** 422 로 죽는다 — 루트 파일은 구분자가 없어 우연히 통과해서
   * 폴더를 붙여 보고도 한참 모른 채 지나간다.
   */
  const toRelativePath = (absolutePath: string): string =>
    relative(canonicalRoot, absolutePath).split(sep).join("/");

  const warmCacheFor = (absolutePath: string): void => {
    const relativePath = toRelativePath(absolutePath);
    if (!isPathAllowed(relativePath)) {
      return;
    }
    try {
      resolveWithinRoot(canonicalRoot, relativePath);
    } catch (err) {
      if (err instanceof RootEscapeError) {
        return;
      }
      throw err;
    }
    try {
      const stats = statSync(absolutePath);
      if (stats.size > maxFileBytes) {
        return;
      }
    } catch {
      return;
    }
    const hash = hashFileContent(absolutePath);
    if (hash !== null) {
      contentHashCache.set(relativePath, hash);
    }
  };

  const flush = (relativePath: string): void => {
    const entry = pending.get(relativePath);
    if (!entry) {
      return;
    }
    pending.delete(relativePath);

    if (entry.changeType === "DELETE") {
      const hash = contentHashCache.get(relativePath);
      contentHashCache.delete(relativePath);

      if (!hash) {
        emitDelete(relativePath, entry.absolutePath);
        return;
      }

      const timer = setTimeout(() => {
        pendingDeletes.delete(hash);
        emitDelete(relativePath, entry.absolutePath);
      }, moveCorrelationWindowMs);
      pendingDeletes.set(hash, { relativePath, absolutePath: entry.absolutePath, timer });
      return;
    }

    const hash = hashFileContent(entry.absolutePath);
    if (hash === null) {
      return;
    }

    if (entry.changeType === "CREATE") {
      const matchedDelete = pendingDeletes.get(hash);
      if (matchedDelete) {
        clearTimeout(matchedDelete.timer);
        pendingDeletes.delete(hash);
        contentHashCache.set(relativePath, hash);
        onChange({
          relativePath,
          changeType: "MOVE",
          absolutePath: entry.absolutePath,
          previousRelativePath: matchedDelete.relativePath,
          contentHash: hash,
        });
        return;
      }
    }

    contentHashCache.set(relativePath, hash);
    onChange({
      relativePath,
      changeType: entry.changeType,
      absolutePath: entry.absolutePath,
      contentHash: hash,
    });
  };

  const schedule = (relativePath: string, changeType: PendingChangeType, absolutePath: string): void => {
    const existing = pending.get(relativePath);
    if (existing) {
      clearTimeout(existing.timer);
    }
    const timer = setTimeout(() => flush(relativePath), debounceMs);
    pending.set(relativePath, { timer, changeType, absolutePath });
  };

  const handleRawEvent = (rawEvent: RawEvent, absolutePath: string): void => {
    if (!isReady && rawEvent === "add" && !emitExisting) {
      warmCacheFor(absolutePath);
      return;
    }

    const relativePath = toRelativePath(absolutePath);

    if (!isPathAllowed(relativePath)) {
      return;
    }

    try {
      resolveWithinRoot(canonicalRoot, relativePath);
    } catch (err) {
      if (err instanceof RootEscapeError) {
        return;
      }
      throw err;
    }

    if (rawEvent !== "unlink") {
      try {
        const stats = statSync(absolutePath);
        if (stats.size > maxFileBytes) {
          return;
        }
      } catch {
        return;
      }
    }

    schedule(relativePath, RAW_TO_CHANGE_TYPE[rawEvent], absolutePath);
  };

  const watcher: FSWatcher = chokidar.watch(canonicalRoot, { ignoreInitial: false, atomic: false });
  watcher.on("add", (p: string) => handleRawEvent("add", p));
  watcher.on("change", (p: string) => handleRawEvent("change", p));
  watcher.on("unlink", (p: string) => handleRawEvent("unlink", p));

  await new Promise<void>((resolve, reject) => {
    watcher.once("ready", () => {
      isReady = true;
      resolve();
    });
    watcher.once("error", reject);
  });

  return {
    async close() {
      for (const entry of pending.values()) {
        clearTimeout(entry.timer);
      }
      pending.clear();
      for (const entry of pendingDeletes.values()) {
        clearTimeout(entry.timer);
      }
      pendingDeletes.clear();
      contentHashCache.clear();
      await watcher.close();
    },
  };
}
