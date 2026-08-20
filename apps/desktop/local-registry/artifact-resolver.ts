/**
 * Agent 2 Spec 35번 Open Local Original의 핵심 안전 로직.
 * artifact_id(mount-relative path) -> registry에서 mount 조회 -> canonical
 * root 기준으로 다시 검증(path-guard 재사용) -> 실제 절대경로 반환.
 *
 * 절대경로 자체를 렌더러/서버로 내보내지 않는다 — 이 함수의 반환값은
 * Electron main process 내부(실제 OS open 호출 직전)에서만 쓰인다.
 */

import { existsSync } from "node:fs";

import { resolveWithinRoot } from "../security/path-guard.js";
import type { LocalRegistryStore } from "./store.js";

export class TrackedArtifactNotFoundError extends Error {}

export async function resolveTrackedArtifactPath(
  registry: LocalRegistryStore,
  localMountHandle: string,
  relativePath: string
): Promise<string> {
  const record = await registry.get(localMountHandle);
  if (!record) {
    throw new TrackedArtifactNotFoundError(`no local mount registered for handle ${localMountHandle}`);
  }

  const absolutePath = resolveWithinRoot(record.canonicalRootPath, relativePath);

  if (!existsSync(absolutePath)) {
    throw new TrackedArtifactNotFoundError(`tracked artifact no longer exists: ${relativePath}`);
  }

  return absolutePath;
}
