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
import { relative } from "node:path";

import { DEBOUNCE_MS, MAX_FILE_BYTES, isWatchedPath } from "./filters.js";
import { RootEscapeError, resolveWithinRoot } from "../security/path-guard.js";

export type LocalChangeType = "CREATE" | "UPDATE" | "DELETE" | "MOVE";

export interface LocalChangeEvent {
  relativePath: string;
  changeType: LocalChangeType;
  absolutePath: string;
  previousRelativePath?: string;
}

export interface LocalWatcherOptions {
  debounceMs?: number;
  maxFileBytes?: number;
  moveCorrelationWindowMs?: number;
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

  const pending = new Map<string, PendingEntry>();
  const contentHashCache = new Map<string, string>();
  const pendingDeletes = new Map<string, PendingDeleteEntry>();

  const emitDelete = (relativePath: string, absolutePath: string): void => {
    onChange({ relativePath, changeType: "DELETE", absolutePath });
  };

  let isReady = false;

  const warmCacheFor = (absolutePath: string): void => {
    const relativePath = relative(canonicalRoot, absolutePath);
    if (!isWatchedPath(relativePath)) {
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
        });
        return;
      }
    }

    contentHashCache.set(relativePath, hash);
    onChange({ relativePath, changeType: entry.changeType, absolutePath: entry.absolutePath });
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
    if (!isReady && rawEvent === "add") {
      warmCacheFor(absolutePath);
      return;
    }

    const relativePath = relative(canonicalRoot, absolutePath);

    if (!isWatchedPath(relativePath)) {
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
