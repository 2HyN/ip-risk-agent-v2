/**
 * Local 폴더 watcher. Agent 2 Spec 26번을 구현한다.
 *
 * MUST 대조:
 * - recursive watch: chokidar가 기본 지원
 * - debounce: 자체 구현 (schedule/flush)
 * - temp/swap/build output filter: filters.ts (isWatchedPath)
 * - file size guard: filters.ts (MAX_FILE_BYTES)
 * - CREATE/UPDATE/DELETE normalization: 구현됨
 * - MOVE normalization: 아직 미구현 — Phase F 이전 처리 필요
 * - ignored path skip: filters.ts
 * - symlink escape defense / watcher event root 재검증: path-guard.ts
 */

import chokidar, { type FSWatcher } from "chokidar";
import { statSync } from "node:fs";
import { relative } from "node:path";

import { DEBOUNCE_MS, MAX_FILE_BYTES, isWatchedPath } from "./filters.js";
import { RootEscapeError, resolveWithinRoot } from "../security/path-guard.js";

export type LocalChangeType = "CREATE" | "UPDATE" | "DELETE";

export interface LocalChangeEvent {
  relativePath: string;
  changeType: LocalChangeType;
  absolutePath: string;
}

export interface LocalWatcherOptions {
  debounceMs?: number;
  maxFileBytes?: number;
}

export interface LocalWatcherHandle {
  close(): Promise<void>;
}

interface PendingEntry {
  timer: ReturnType<typeof setTimeout>;
  changeType: LocalChangeType;
  absolutePath: string;
}

type RawEvent = "add" | "change" | "unlink";

const RAW_TO_CHANGE_TYPE: Record<RawEvent, LocalChangeType> = {
  add: "CREATE",
  change: "UPDATE",
  unlink: "DELETE",
};

export async function startLocalWatcher(
  canonicalRoot: string,
  onChange: (event: LocalChangeEvent) => void,
  options: LocalWatcherOptions = {}
): Promise<LocalWatcherHandle> {
  const debounceMs = options.debounceMs ?? DEBOUNCE_MS;
  const maxFileBytes = options.maxFileBytes ?? MAX_FILE_BYTES;

  const pending = new Map<string, PendingEntry>();

  const flush = (relativePath: string): void => {
    const entry = pending.get(relativePath);
    if (!entry) {
      return;
    }
    pending.delete(relativePath);
    onChange({ relativePath, changeType: entry.changeType, absolutePath: entry.absolutePath });
  };

  const schedule = (relativePath: string, changeType: LocalChangeType, absolutePath: string): void => {
    const existing = pending.get(relativePath);
    if (existing) {
      clearTimeout(existing.timer);
    }
    const timer = setTimeout(() => flush(relativePath), debounceMs);
    pending.set(relativePath, { timer, changeType, absolutePath });
  };

  const handleRawEvent = (rawEvent: RawEvent, absolutePath: string): void => {
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

  const watcher: FSWatcher = chokidar.watch(canonicalRoot, { ignoreInitial: true });
  watcher.on("add", (p: string) => handleRawEvent("add", p));
  watcher.on("change", (p: string) => handleRawEvent("change", p));
  watcher.on("unlink", (p: string) => handleRawEvent("unlink", p));

  await new Promise<void>((resolve, reject) => {
    watcher.once("ready", () => resolve());
    watcher.once("error", reject);
  });

  return {
    async close() {
      for (const entry of pending.values()) {
        clearTimeout(entry.timer);
      }
      pending.clear();
      await watcher.close();
    },
  };
}
