/**
 * Local root escape / symlink escape 방지.
 * Agent 2 Spec 27번: relative path -> canonical root와 join -> realpath ->
 * root의 descendant인지 검증 -> 아니면 deny.
 *
 * 2단계 검증:
 * 1. 문자열 기준(lexical) 검사 — 파일 존재 여부와 무관하게 ../ 탈출을
 *    즉시 잡는다. 중간 경로가 통째로 존재하지 않는 깊은 탈출 시도에도
 *    안전하다.
 * 2. symlink 방어 — 실제로 존재하는 가장 가까운 조상 디렉터리까지
 *    올라가며 realpath로 검증한다. 문자열 검사로는 symlink가 실제로
 *    어디를 가리키는지 알 수 없기 때문에 별도로 필요하다.
 */

import { realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative } from "node:path";

export class RootEscapeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RootEscapeError";
  }
}

export function resolveWithinRoot(canonicalRoot: string, relativePath: string): string {
  if (isAbsolute(relativePath)) {
    throw new RootEscapeError(`relative path must not be absolute: ${relativePath}`);
  }

  const resolvedRoot = realpathSync(canonicalRoot);
  const joined = join(resolvedRoot, relativePath);

  // 1단계: 문자열 기준 검사. 존재하지 않는 경로에도 항상 동작한다.
  const lexicalRel = relative(resolvedRoot, joined);
  if (lexicalRel !== "" && (lexicalRel.startsWith("..") || isAbsolute(lexicalRel))) {
    throw new RootEscapeError(`path escapes root: ${relativePath}`);
  }

  // 2단계: symlink 방어. 실제로 존재하는 가장 가까운 조상까지 올라간다.
  let current = joined;
  for (;;) {
    try {
      const resolvedTarget = realpathSync(current);
      const finalRel = relative(resolvedRoot, resolvedTarget);
      const isRootItself = finalRel === "";
      if (!isRootItself && (finalRel.startsWith("..") || isAbsolute(finalRel))) {
        throw new RootEscapeError(`path escapes root: ${relativePath}`);
      }
      if (current === joined) {
        return resolvedTarget;
      }
      const remainder = relative(current, joined);
      return join(resolvedTarget, remainder);
    } catch (err) {
      if (err instanceof RootEscapeError) {
        throw err;
      }
      const parent = dirname(current);
      if (parent === current) {
        throw new RootEscapeError(`unable to resolve path safely: ${relativePath}`);
      }
      current = parent;
    }
  }
}
