import type { LocalChangeEvent } from "../watcher/watcher.js";

export interface EventReporter {
  report(event: LocalChangeEvent): Promise<void>;
}

export class RetryingDesktopEventQueue {
  private readonly pending: LocalChangeEvent[] = [];
  private draining: Promise<void> | null = null;
  private retryAttempt = 0;

  constructor(
    private readonly reporter: EventReporter,
    private readonly delay: (milliseconds: number) => Promise<void> = (milliseconds) =>
      new Promise((resolve) => setTimeout(resolve, milliseconds)),
    private readonly maximumPending = 1000,
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
      } catch {
        const wait = Math.min(30_000, 500 * 2 ** Math.min(this.retryAttempt, 6));
        this.retryAttempt += 1;
        await this.delay(wait);
      }
    }
  }
}
