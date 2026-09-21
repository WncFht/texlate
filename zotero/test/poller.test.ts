import { assert } from "chai";
import {
  ApiError,
  NetworkError,
  TimeoutError,
  type TaskSnapshot,
  type TexlateClient,
} from "../src/contracts";
import { phaseKey, pollTask } from "../src/modules/poller";

function snap(status: string, stage?: string): TaskSnapshot {
  return {
    task_id: "t_test",
    kind: "arxiv",
    status,
    progress: 0,
    message: "",
    stage,
    created_at: 0,
    updated_at: 0,
    counters: { total: 0, done: 0, cached: 0, failed: 0, tokens: 0 },
    error: null,
    warnings: [],
    artifacts: {},
    last_seq: 0,
  } as TaskSnapshot;
}

/** Scripted getTask — each call pops a step; the last step repeats forever. */
function fakeClient(steps: Array<TaskSnapshot | Error>): {
  client: TexlateClient;
  calls: () => number;
} {
  let calls = 0;
  const client = {
    getTask: async (_taskId: string): Promise<TaskSnapshot> => {
      calls += 1;
      const step = steps[Math.min(calls - 1, steps.length - 1)];
      if (step instanceof Error) throw step;
      return step;
    },
  } as unknown as TexlateClient;
  return { client, calls: () => calls };
}

const FAST = { intervalMs: 1, timeoutMs: 60_000 };

async function rejection(p: Promise<unknown>): Promise<unknown> {
  try {
    await p;
  } catch (e) {
    return e;
  }
  assert.fail("expected pollTask to reject");
}

describe("poller", function () {
  it("resolves on terminal status and fires onProgress per snapshot", async function () {
    const seen: string[] = [];
    const { client, calls } = fakeClient([
      snap("queued"),
      snap("translating"),
      snap("done"),
    ]);
    const out = await pollTask(client, "t_test", {
      ...FAST,
      onProgress: (s) => seen.push(s.status),
    });
    assert.equal(out.status, "done");
    assert.equal(calls(), 3);
    assert.deepEqual(seen, ["queued", "translating", "done"]);
  });

  it("retries retryable failures and resets the consecutive counter", async function () {
    // Every retryable class is exercised; interleaved successes reset the
    // counter, so this sequence must NOT hit MAX_CONSECUTIVE_FAILURES.
    const { client, calls } = fakeClient([
      new NetworkError("refused"),
      snap("queued"),
      new TimeoutError("timed out"),
      new ApiError(503, "busy"),
      snap("done"),
    ]);
    const out = await pollTask(client, "t_test", FAST);
    assert.equal(out.status, "done");
    assert.equal(calls(), 5);
  });

  it("aborts after MAX_CONSECUTIVE_FAILURES in a row", async function () {
    const { client, calls } = fakeClient([new NetworkError("down")]);
    const err = await rejection(pollTask(client, "t_test", FAST));
    assert.instanceOf(err, NetworkError);
    // 5 tolerated retries; the 6th consecutive failure rethrows.
    assert.equal(calls(), 6);
  });

  it("fails fast on ApiError 4xx — never retried", async function () {
    const { client, calls } = fakeClient([
      new ApiError(404, '{"detail":"no such task"}'),
      snap("done"),
    ]);
    const err = await rejection(pollTask(client, "t_test", FAST));
    assert.instanceOf(err, ApiError);
    assert.equal(calls(), 1);
  });

  it("throws on unknown status strings (protocol bug, not retried)", async function () {
    const { client, calls } = fakeClient([snap("frobnicate"), snap("done")]);
    const err = await rejection(pollTask(client, "t_test", FAST));
    assert.instanceOf(err, Error);
    assert.match((err as Error).message, /unknown task status frobnicate/);
    assert.equal(calls(), 1);
  });

  it("times out with TimeoutError once the deadline passes", async function () {
    const { client } = fakeClient([snap("translating")]);
    const err = await rejection(
      pollTask(client, "t_test", { intervalMs: 1, timeoutMs: 5 }),
    );
    assert.instanceOf(err, TimeoutError);
    assert.match((err as Error).message, /still translating/);
  });

  it("phaseKey: terminal status beats a stale stage; stage beats status", function () {
    // Terminal wins even when the snapshot still carries a stage value.
    assert.equal(phaseKey(snap("done", "compiling")), "done");
    assert.equal(phaseKey(snap("translating", "parsing")), "parsing");
    assert.equal(phaseKey(snap("queued")), "queued");
    // Unknown/absent stage falls back to the status name.
    assert.equal(phaseKey(snap("translating", "bogus-stage")), "translating");
    assert.equal(phaseKey(snap("translating")), "translating");
  });
});
