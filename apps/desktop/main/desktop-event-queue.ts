import type { LocalChangeEvent } from "../watcher/watcher.js";

export interface EventReporter {
  report(event: LocalChangeEvent): Promise<void>;
}

/**
 * 실패를 어디에 알릴지. 기본은 터미널이다.
 *
 * 예전에는 `catch {}` 로 삼키고 영원히 재시도했다. 서버가 거절해도 사용자에게는
 * **아무 일도 일어나지 않는 것처럼** 보인다 — 폴더를 연결했는데 파일이 영영 올라
 * 오지 않고 터미널에도 아무것도 없었다.
 */
export type QueueFailureSink = (message: string) => void;

export class RetryingDesktopEventQueue {
  private readonly pending: LocalChangeEvent[] = [];
  private draining: Promise<void> | null = null;
  private retryAttempt = 0;

  constructor(
    private readonly reporter: EventReporter,
    private readonly delay: (milliseconds: number) => Promise<void> = (milliseconds) =>
      new Promise((resolve) => setTimeout(resolve, milliseconds)),
    private readonly maximumPending = 1000,
    private readonly onFailure: QueueFailureSink = (message) => console.error(message),
  ) {}

  enqueue(event: LocalChangeEvent): void {
    if (this.pending.length >= this.maximumPending) {
      throw new Error("desktop event queue capacity was reached");
    }
    this.pending.push(event);
    this.draining ??= this.drain().finally(() => {
      this.draining = null;
      if (this.pending.length > 0) this.enqueueDrain();
    });
  }

  async whenIdle(): Promise<void> {
    await this.draining;
  }

  private enqueueDrain(): void {
    this.draining ??= this.drain().finally(() => {
      this.draining = null;
      if (this.pending.length > 0) this.enqueueDrain();
    });
  }

  private async drain(): Promise<void> {
    while (this.pending.length > 0) {
      const event = this.pending[0];
      if (event === undefined) return;
      try {
        await this.reporter.report(event);
        this.pending.shift();
        this.retryAttempt = 0;
      } catch (reason) {
        const wait = Math.min(30_000, 500 * 2 ** Math.min(this.retryAttempt, 6));
        // 첫 실패와 그 뒤 여덟 번마다 알린다. 매번 적으면 재시도가 화면을 덮고,
        // 한 번만 적으면 계속 막혀 있는 것인지 알 수 없다. 경로는 적지 않는다 —
        // 사용자의 폴더 안이다.
        if (this.retryAttempt % 8 === 0) {
          const detail = reason instanceof Error ? reason.message : String(reason);
          this.onFailure(
            `desktop event not delivered (${event.changeType}, attempt ${this.retryAttempt + 1}): ${detail}`,
          );
        }
        this.retryAttempt += 1;
        await this.delay(wait);
      }
    }
  }
}
