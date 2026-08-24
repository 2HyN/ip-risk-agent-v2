import { useEffect, useState } from "react";

import type { AnalysisProgress } from "../api/types";

/**
 * 작업 현황 폴링.
 *
 * 분석은 화면 밖(worker)에서 돌므로 화면이 주기적으로 물어야 한다. 실패한 폴링은
 * 조용히 넘어가고 다음 주기에 다시 묻는다 — 일시적인 네트워크 문제로 진행 바가
 * 오류 화면으로 바뀌면 그쪽이 더 시끄럽다.
 */
export function useAnalysisProgress(
  load: () => Promise<AnalysisProgress>,
  intervalMs = 5_000,
): AnalysisProgress | null {
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    async function poll(): Promise<void> {
      try {
        const next = await load();
        if (!cancelled) setProgress(next);
      } catch {
        // 다음 주기에 다시 묻는다.
      }
      if (!cancelled) timer = window.setTimeout(() => void poll(), intervalMs);
    }
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [load, intervalMs]);
  return progress;
}
