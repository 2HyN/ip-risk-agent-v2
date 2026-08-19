/**
 * Watcher 필터/디바운스 설정.
 * Agent 2 Spec 26번(recursive watch, debounce, temp/build output filter).
 *
 * Sora3780/ip-risk-agent (팀 공개 저장소)의 detect.py/watcher.py에 있던
 * 검증된 필터 규칙(제외 폴더, 임시파일 패턴, 확장자 분류)을 TypeScript로
 * 옮겼다 — 로직만 참고했고 실행 코드 자체는 새로 작성했다.
 */

import { extname } from "node:path";

export const SKIP_DIRS = new Set([".git", ".venv", "venv", "__pycache__", "node_modules", ".idea"]);

export const CODE_EXTENSIONS = new Set([
  ".py", ".js", ".ts", ".java", ".go", ".c", ".h", ".cpp", ".rs",
]);

export const DOC_EXTENSIONS = new Set([".md", ".txt", ".rst"]);

export const WATCH_NAMES = new Set([
  "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
  "package.json", "README.md", "LICENSE", "LICENSE.md", "NOTICE",
]);

const TEMP_SUFFIXES = [".swp", ".swx", ".tmp", "~", ".part", ".crdownload"];

export const DEBOUNCE_MS = 3000;
export const MAX_FILE_BYTES = 1_000_000;

export function isWatchedPath(relativePath: string): boolean {
  const parts = relativePath.split(/[\\/]/).filter((part) => part.length > 0);
  if (parts.length === 0) {
    return false;
  }

  const dirParts = parts.slice(0, -1);
  if (dirParts.some((part) => SKIP_DIRS.has(part) || part.startsWith("."))) {
    return false;
  }

  const name = parts[parts.length - 1] ?? "";
  if (name.startsWith(".") || TEMP_SUFFIXES.some((suffix) => name.endsWith(suffix))) {
    return false;
  }
  if (/^\d+$/.test(name)) {
    return false;
  }

  const suffix = extname(name).toLowerCase();
  return WATCH_NAMES.has(name) || CODE_EXTENSIONS.has(suffix) || DOC_EXTENSIONS.has(suffix);
}
