/**
 * Watcher 필터/디바운스 설정.
 * Agent 2 Spec 26번(recursive watch, debounce, temp/build output filter).
 *
 * **표를 여기서 적지 않는다.** 서버가 쓰는 표에서 생성한다
 * (`scripts/generate_source_filters.py`). 예전에는 여기 손으로 적었고 이미 크게
 * 어긋나 있었다 — 코드 확장자 9 대 29, 문서 3 대 21, 제외 폴더 6 대 23이었고
 * `requirements.lock` · `constraints.txt` 를 감시하지 않았다. 0-J 가 되살려 낸
 * 이름들이다.
 *
 * **감시가 먼저 거른다.** 서버 표를 넓혀도 데스크톱이 안 보내면 그 파일은 Local
 * 마운트에서 존재하지 않는다.
 */

import { extname } from "node:path";

import {
  CODE_EXTENSIONS as GENERATED_CODE_EXTENSIONS,
  DEPENDENCY_DIRECTORY,
  DEPENDENCY_EXACT_NAMES,
  DEPENDENCY_PREFIX,
  DOCUMENT_EXTENSIONS as GENERATED_DOCUMENT_EXTENSIONS,
  EXTENSIONLESS_TEXT,
  LICENCE_STEMS,
  SKIP_DIRECTORIES,
} from "./generated-filters.js";

export const SKIP_DIRS = new Set(SKIP_DIRECTORIES);
export const CODE_EXTENSIONS = new Set(GENERATED_CODE_EXTENSIONS);
export const DOC_EXTENSIONS = new Set(GENERATED_DOCUMENT_EXTENSIONS);

const TEMP_SUFFIXES = [".swp", ".swx", ".tmp", "~", ".part", ".crdownload"];

export const DEBOUNCE_MS = 3000;
export const MAX_FILE_BYTES = 1_000_000;

/**
 * 의존성 선언인가. 서버의 `dependency_files.dependency_format` 과 같은 판단이다.
 *
 * 예전에는 이 파일들을 **감시 대상에서 뺐다** — "License 판별을 크게 손볼 예정" 이라는
 * 이유였다. 그 손보기가 끝났으므로(0 단계 · 2 단계) 되돌린다. 그때까지 Local 마운트는
 * 라이선스 위험을 **하나도** 만들지 못했다.
 *
 * 라이선스 경로는 KIPRIS 를 쓰지 않으므로 이 파일들을 보는 데 특허 한도가 들지 않는다.
 */
function isDependencyDeclaration(name: string, dirParts: readonly string[]): boolean {
  if (DEPENDENCY_EXACT_NAMES.includes(name)) {
    return true;
  }
  if (name.startsWith(DEPENDENCY_PREFIX)) {
    return name.endsWith(".txt") || name.endsWith(".in") || name.endsWith(".lock");
  }
  // `requirements/base.txt` 처럼 폴더가 형식을 말해 주는 관행. 이름만 보면 `base.txt`
  // 라 알아볼 수 없다.
  const parent = dirParts[dirParts.length - 1];
  if (parent === DEPENDENCY_DIRECTORY) {
    return name.endsWith(".txt") || name.endsWith(".in");
  }
  return false;
}

/** 라이선스 전문 파일인가. 어느 분석기도 맡지 않으므로 감시하지 않는다 (결함 26). */
function isLicenceText(name: string): boolean {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  return LICENCE_STEMS.includes(stem);
}

export function isWatchedPath(relativePath: string): boolean {
  const parts = relativePath.split(/[\\/]/).filter((part) => part.length > 0);
  if (parts.length === 0) {
    return false;
  }

  const dirParts = parts.slice(0, -1);
  if (dirParts.some((part) => SKIP_DIRS.has(part) || part.startsWith("."))) {
    return false;
  }

  const name = (parts[parts.length - 1] ?? "").toLowerCase();
  if (name.startsWith(".") || TEMP_SUFFIXES.some((suffix) => name.endsWith(suffix))) {
    return false;
  }
  if (/^\d+$/.test(name)) {
    return false;
  }
  if (isLicenceText(name)) {
    return false;
  }
  if (isDependencyDeclaration(name, dirParts)) {
    return true;
  }
  if (EXTENSIONLESS_TEXT.includes(name)) {
    return true;
  }
  const suffix = extname(name).toLowerCase();
  return CODE_EXTENSIONS.has(suffix) || DOC_EXTENSIONS.has(suffix);
}
