import {
  ApiError,
  isActiveStatus,
  isTerminalStatus,
  NetworkError,
  STAGES,
  TimeoutError,
  type PollOptions,
  type TaskSnapshot,
  type TexlateClient,
} from "../contracts";
import { sleep } from "../utils/misc";

/**
 * poller.ts — setTimeout polling of GET /api/task/{id} until terminal status.
 * Plugin sandbox has no EventSource/AbortController — polling is the only
 * progress channel. Transport failures (NetworkError, request TimeoutError,
 * ApiError 5xx) retry up to MAX_CONSECUTIVE_FAILURES in a row — the server
 * may restart mid-task. ApiError 4xx and unknown status strings fail fast:
 * bad id / protocol bug, never retryable.
 */

const MAX_CONSECUTIVE_FAILURES = 5;

function isRetryableError(err: unknown): boolean {
  if (err instanceof NetworkError || err instanceof TimeoutError) return true;
  if (err instanceof ApiError) return err.status >= 500;
  return false;
}

export async function pollTask(
  client: TexlateClient,
  taskId: string,
  opts: PollOptions,
): Promise<TaskSnapshot> {
  const start = Date.now();
  let consecutiveFailures = 0;
  let lastStatus = "unseen";

  for (;;) {
    if (Date.now() - start > opts.timeoutMs) {
      throw new TimeoutError(
        `task ${taskId} still ${lastStatus} after ${opts.timeoutMs}ms`,
      );
    }

    let snap: TaskSnapshot;
    try {
      snap = await client.getTask(taskId);
    } catch (err) {
      if (!isRetryableError(err)) throw err;
      consecutiveFailures += 1;
      if (consecutiveFailures > MAX_CONSECUTIVE_FAILURES) throw err;
      await sleep(opts.intervalMs);
      continue;
    }
    consecutiveFailures = 0;

    if (!isActiveStatus(snap.status) && !isTerminalStatus(snap.status)) {
      throw new Error(`unknown task status ${String(snap.status)}`);
    }
    lastStatus = snap.status;
    opts.onProgress?.(snap);
    if (isTerminalStatus(snap.status)) return snap;

    await sleep(opts.intervalMs);
  }
}

/**
 * ftl message-key suffix for progress text: stage name when the snapshot
 * carries a known stage, otherwise the status name (covers "queued" and all
 * terminal states).
 */
export function phaseKey(snap: TaskSnapshot): string {
  // Terminal wins over a stale stage — server NULLs stage on terminal
  // transition today, but phaseKey shouldn't rely on that invariant.
  if (isTerminalStatus(snap.status)) return snap.status;
  if (
    typeof snap.stage === "string" &&
    (STAGES as readonly string[]).includes(snap.stage)
  ) {
    return snap.stage;
  }
  return snap.status;
}
