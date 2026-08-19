/**
 * Local root escape / symlink escape 방지.
 * Agent 2 Spec 27번: relative path -> canonical root와 join -> realpath ->
 * root의 descendant인지 검증 -> 아니면 deny.
 *
 * realpath()는 symlink를 실제 목적지로 풀어내므로, root 안의 symlink가
 * root 밖을 가리켜도 이 함수가 그 실제 경로를 보고 거부할 수 있다.
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

  let resolvedTarget: string;
  try {
    resolvedTarget = realpathSync(joined);
  } catch {
    const resolvedParentDir = realpathSync(dirname(joined));
    resolvedTarget = join(resolvedParentDir, relativePath.split(/[\\/]/).pop() ?? "");
  }

  const rel = relative(resolvedRoot, resolvedTarget);
  const isRootItself = rel === "";
  const escapes = !isRootItself && (rel.startsWith("..") || isAbsolute(rel));

  if (escapes) {
    throw new RootEscapeError(`path escapes root: ${relativePath}`);
  }

  return resolvedTarget;
}
