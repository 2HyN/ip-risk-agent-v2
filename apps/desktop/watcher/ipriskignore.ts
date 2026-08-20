/**
 * Source-level .ipriskignore 파싱/매칭. Agent 2 Spec §28.
 *
 * VWS 전역 .ipriskignore(Agent 1 SecurityGate 책임)와는 다른, 로컬 폴더
 * 자체에 있는 optional deny 목록이다. Python(GitHub) 쪽과 같은 원칙으로
 * fnmatch 스타일 글롭 매칭('*'가 경로 구분자도 매치)을 그대로 흉내냈다.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

export function parseIpriskignore(content: string): string[] {
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));
}

export function loadIpriskignorePatterns(canonicalRoot: string): string[] {
  try {
    const content = readFileSync(join(canonicalRoot, ".ipriskignore"), "utf-8");
    return parseIpriskignore(content);
  } catch {
    return [];
  }
}

function globToRegExp(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`);
}

export function isDeniedByIpriskignore(relativePath: string, patterns: string[]): boolean {
  return patterns.some((pattern) => globToRegExp(pattern).test(relativePath));
}
