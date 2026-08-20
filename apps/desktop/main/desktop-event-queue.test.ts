import assert from "node:assert/strict";
import test from "node:test";

import type { LocalChangeEvent } from "../watcher/watcher.js";
import { RetryingDesktopEventQueue } from "./desktop-event-queue.js";

test("offline Desktop events remain ordered and are retransmitted", async () => {
  const delivered: string[] = [];
  let failures = 1;
  const queue = new RetryingDesktopEventQueue(
    {
      report: async (event) => {
        if (failures > 0) {
          failures -= 1;
          throw new Error("offline");
        }
        delivered.push(event.relativePath);
      },
    },
    async () => undefined,
  );
  const first: LocalChangeEvent = { relativePath: "first.py", absolutePath: "C:/private/first.py", changeType: "UPDATE" };
  const second: LocalChangeEvent = { relativePath: "second.py", absolutePath: "C:/private/second.py", changeType: "UPDATE" };

  queue.enqueue(first);
  queue.enqueue(second);
  await queue.whenIdle();

  assert.deepEqual(delivered, ["first.py", "second.py"]);
});
