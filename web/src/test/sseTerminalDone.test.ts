// 终态收敛兜底：done 帧未达（SSE 终态 snapshot 先行关流 / 轮询终态 /
// 探活终态）也要合成 live.done——Reader 的 loadReader 只挂 done 触发，
// 缺席即终态任务永卡 "loading"（B12 review 确证缺陷）。

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

import type { TaskEventHandlers, TaskSnapshot } from "../api/client";
import { taskStore } from "../stores/tasks";

const snap = (
    id: string,
    status: TaskSnapshot["status"],
): TaskSnapshot => ({
    task_id: id,
    kind: "arxiv",
    status,
    progress: status === "done" ? 100 : 40,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    artifacts:
        status === "done" ? { zh_pdf: `/api/files/${id}/zh.pdf` } : undefined,
});

const handlersOf = (i: number) =>
    mocks.openTaskEvents.mock.calls[i][1] as TaskEventHandlers;

const used: string[] = [];

beforeEach(() => {
    vi.useFakeTimers();
    used.length = 0;
    mocks.tasks.mockReset();
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

describe("终态收敛兜底（live.done 合成）", () => {
    it("SSE snapshot 帧带终态——真实 done 帧随 close() 丢在线路上 → 合成 live.done", async () => {
        mocks.tasks.mockResolvedValue([snap("t1", "translating")]);
        used.push("t1");
        await taskStore.refresh();

        handlersOf(0).snapshot?.(snap("t1", "done"));

        expect(taskStore.task("t1")!.status).toBe("done");
        const done = taskStore.live("t1")!.done;
        expect(done?.status).toBe("done");
        expect(done?.artifacts.zh_pdf).toBe("/api/files/t1/zh.pdf");
    });

    it("槽外轮询任务探到终态 → 合成 live.done（轮询路本无 done 帧）", async () => {
        mocks.tasks.mockResolvedValue([]);
        // done impl 必须先挂——watch→rebalance→startPoll 的首轮 tick 同步发起
        mocks.snapshot.mockImplementation((id: string) =>
            Promise.resolve(snap(id, "done")),
        );
        used.push("p1", "p2", "p3", "p4");
        taskStore.watch("p1");
        taskStore.watch("p2");
        taskStore.watch("p3");
        taskStore.watch("p4"); // 第 4 个 pin——槽满降级轮询
        await vi.advanceTimersByTimeAsync(0); // p4 首轮 tick
        expect(taskStore.live("p4")!.done?.status).toBe("done");
    });

    it("SSE 服务端终结 + 探活终态 → 合成 live.done", async () => {
        mocks.tasks.mockResolvedValue([snap("f1", "translating")]);
        used.push("f1");
        await taskStore.refresh();
        mocks.snapshot.mockResolvedValue(snap("f1", "done"));
        handlersOf(0).transport?.("closed");
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.live("f1")!.done?.status).toBe("done");
    });

    it("已送达的真 done 不被迟到终态快照覆盖（stats 保真）", async () => {
        mocks.tasks.mockResolvedValue([snap("d1", "translating")]);
        used.push("d1");
        await taskStore.refresh();
        const h = handlersOf(0);
        h.done?.({
            status: "done",
            artifacts: { zh_pdf: "/api/files/d1/zh.pdf" },
            stats: { seconds: 7 },
        });
        h.snapshot?.({ ...snap("d1", "done"), artifacts: {} });
        expect(taskStore.live("d1")!.done?.stats.seconds).toBe(7);
        expect(taskStore.live("d1")!.done?.artifacts.zh_pdf).toBe(
            "/api/files/d1/zh.pdf",
        );
    });
});
