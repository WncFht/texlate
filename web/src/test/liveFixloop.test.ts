// progress chrome 一轮覆盖：fixloop/l2 SSE 帧 → TaskLive 合并语义。
//  round 帧按 round 号去重 append；done 帧 cell/旧裸 cell 两形态归一；
//  l2 整帧存、phase 缺省按 done；终态收敛不清这两个字段。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    snapshot: vi.fn(),
    openTaskEvents: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            tasks: mocks.tasks,
            snapshot: mocks.snapshot,
        },
        openTaskEvents: mocks.openTaskEvents,
    };
});

import type {
    DoneEvent,
    L2Event,
    TaskEventHandlers,
    TaskSnapshot,
} from "../api/client";
import { taskStore } from "../stores/tasks";

const snap = (
    id: string,
    status: TaskSnapshot["status"],
    updated = 0,
): TaskSnapshot => ({
    task_id: id,
    kind: "arxiv",
    status,
    progress: status === "done" ? 100 : 40,
    created_at: 1_700_000_000,
    updated_at: updated || 1_700_000_000,
});

const handlersOf = (i: number) =>
    mocks.openTaskEvents.mock.calls[i][1] as TaskEventHandlers;

const used: string[] = [];

const doneEv: DoneEvent = { status: "done", artifacts: {}, stats: {} };

beforeEach(() => {
    vi.useFakeTimers();
    used.length = 0;
    mocks.tasks.mockReset().mockResolvedValue([]);
    mocks.snapshot
        .mockReset()
        .mockImplementation((id: string) =>
            Promise.resolve(snap(id, "translating")),
        );
    mocks.openTaskEvents.mockReset().mockImplementation(() => {
        const ch = {
            closed: false,
            close: vi.fn(() => {
                ch.closed = true;
            }),
        };
        return ch;
    });
});

afterEach(() => {
    for (const id of used) taskStore.unwatch(id);
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe("fixloop 帧合并", () => {
    it("round 帧按 round 号 append；同号帧顶替（不重复入列）", async () => {
        used.push("f1");
        taskStore.watch("f1");
        const h = handlersOf(0);
        h.fixloop?.({
            phase: "round",
            round: { round: 1, n_errors: 5, category: "missing_file" },
        });
        h.fixloop?.({
            phase: "round",
            round: { round: 2, n_errors: 2, sec: 3.5 },
        });
        h.fixloop?.({
            phase: "round",
            round: { round: 2, n_errors: 2, sec: 4.1, died: true },
        });
        const f = taskStore.live("f1")!.fixloop!;
        expect(f.done).toBe(false);
        expect(f.rounds).toEqual([
            { round: 1, n_errors: 5, category: "missing_file" },
            { round: 2, n_errors: 2, sec: 4.1, died: true },
        ]);
    });

    it("done 帧 cell 落定 verdict/floor_restored/rounds", async () => {
        used.push("f2");
        taskStore.watch("f2");
        const h = handlersOf(0);
        h.fixloop?.({
            phase: "round",
            round: { round: 1, n_errors: 3 },
        });
        h.fixloop?.({
            phase: "done",
            cell: {
                rounds: [
                    { round: 1, n_errors: 3 },
                    { round: 2, n_errors: 0, sec: 1.2 },
                ],
                verdict: "clean",
                floor_restored: false,
                actions: [],
            },
        });
        const f = taskStore.live("f2")!.fixloop!;
        expect(f.done).toBe(true);
        expect(f.verdict).toBe("clean");
        expect(f.floor_restored).toBe(false);
        expect(f.rounds).toHaveLength(2);
    });

    it("旧裸 cell（无 phase，键平铺顶层）按 done 处理", async () => {
        used.push("f3");
        taskStore.watch("f3");
        handlersOf(0).fixloop?.({
            rounds: [{ round: 1, n_errors: 1 }],
            verdict: "max_rounds",
            floor_restored: true,
        });
        const f = taskStore.live("f3")!.fixloop!;
        expect(f.done).toBe(true);
        expect(f.verdict).toBe("max_rounds");
        expect(f.floor_restored).toBe(true);
        expect(f.rounds).toEqual([{ round: 1, n_errors: 1 }]);
    });

    it("done 帧 cell 不带 rounds → 保留 round 帧累积的 rounds", async () => {
        used.push("f4");
        taskStore.watch("f4");
        const h = handlersOf(0);
        h.fixloop?.({ phase: "round", round: { round: 1, n_errors: 2 } });
        h.fixloop?.({ phase: "done", cell: { verdict: "stuck" } });
        const f = taskStore.live("f4")!.fixloop!;
        expect(f.done).toBe(true);
        expect(f.rounds).toEqual([{ round: 1, n_errors: 2 }]);
    });

    it("终态收敛不清 fixloop（终态面板要显示）", async () => {
        used.push("f5");
        taskStore.watch("f5");
        const h = handlersOf(0);
        h.fixloop?.({
            phase: "done",
            cell: { rounds: [{ round: 1 }], verdict: "clean" },
        });
        h.done?.(doneEv);
        const f = taskStore.live("f5")!.fixloop!;
        expect(f.done).toBe(true);
        expect(f.verdict).toBe("clean");
    });
});

describe("l2 帧合并", () => {
    it("start/progress 帧整帧存（phase 原样）", async () => {
        used.push("l1");
        taskStore.watch("l1");
        handlersOf(0).l2?.({ phase: "progress", message: "3/10" });
        expect(taskStore.live("l1")!.l2).toEqual({
            phase: "progress",
            message: "3/10",
            enabled: undefined,
            errors: undefined,
            retranslated: undefined,
            fallback: undefined,
        });
    });

    it("phase 缺省按 done 归一；统计键平铺", async () => {
        used.push("l2");
        taskStore.watch("l2");
        const ev: L2Event = {
            enabled: true,
            errors: 4,
            retranslated: 3,
            fallback: 1,
        };
        handlersOf(0).l2?.(ev);
        const l = taskStore.live("l2")!.l2!;
        expect(l.phase).toBe("done");
        expect(l.errors).toBe(4);
        expect(l.retranslated).toBe(3);
        expect(l.fallback).toBe(1);
    });

    it("终态收敛不清 l2", async () => {
        used.push("l3");
        taskStore.watch("l3");
        const h = handlersOf(0);
        h.l2?.({ phase: "done", enabled: true, errors: 0 });
        h.done?.(doneEv);
        expect(taskStore.live("l3")!.l2!.errors).toBe(0);
    });
});
