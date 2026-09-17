// fe-live 二轮修复覆盖：
//  M2  unwatch/句柄 close 统一 detach（幂等，轮询路也停）
//  M6  SSE 被服务端终结（transport closed）→ 探活定去留，不复活重连循环
//  M8  transport 新态：首连 connecting / 降级 polling
//      resync 帧：清 chunk 派生态 + 拉快照对齐，不降轮询
//  P2  chunk 帧按 seq 增量写 dense 数组（填洞 pending、非法丢弃）

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

import {
    ApiError,
    type TaskChannel,
    type TaskEventHandlers,
    type TaskSnapshot,
} from "../api/client";
import { POLL_INTERVAL_MS, taskStore } from "../stores/tasks";

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
const channelOf = (i: number) =>
    mocks.openTaskEvents.mock.results[i].value as TaskChannel & {
        close: ReturnType<typeof vi.fn>;
    };
const openedFor = () =>
    mocks.openTaskEvents.mock.calls.map((c) => c[0] as string);

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

describe("M2：watch/unwatch 统一 detach（幂等）", () => {
    it("句柄 close() = unwatch：channel 关闭、closed 翻转、重复 close/unwatch 无副作用", async () => {
        mocks.tasks.mockResolvedValue([snap("u1", "translating", 50)]);
        used.push("u1");
        await taskStore.refresh();
        const h = taskStore.watch("u1");
        h.close();
        expect(h.closed).toBe(true);
        expect(channelOf(0).close).toHaveBeenCalled();
        h.close(); // 幂等
        taskStore.unwatch("u1"); // 公开幂等——已摘除再调不炸
    });

    it("槽外轮询任务 unwatch 后不再 tick（轮询路 detach 同语义）", async () => {
        mocks.tasks.mockResolvedValue([]);
        used.push("x1", "x2", "x3", "x4");
        taskStore.watch("x1");
        taskStore.watch("x2");
        taskStore.watch("x3");
        const h4 = taskStore.watch("x4"); // 槽满 → polling
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.live("x4")!.transport).toBe("polling");
        mocks.snapshot.mockClear();
        h4.close();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
        expect(mocks.snapshot).not.toHaveBeenCalled();
    });
});

describe("M8：transport 状态机", () => {
    it("首连未 open 报 connecting（非 reconnecting）；open 后转 live", async () => {
        mocks.tasks.mockResolvedValue([]);
        used.push("c1");
        taskStore.watch("c1");
        // ensureChannel 落座即 connecting——openTaskEvents 尚未回话
        expect(taskStore.live("c1")!.transport).toBe("connecting");
        handlersOf(0).transport?.("live");
        expect(taskStore.live("c1")!.transport).toBe("live");
    });

    it("槽外任务 startPoll 报 polling", async () => {
        mocks.tasks.mockResolvedValue([]);
        used.push("p1", "p2", "p3", "p4");
        taskStore.watch("p1");
        taskStore.watch("p2");
        taskStore.watch("p3");
        taskStore.watch("p4");
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.live("p4")!.transport).toBe("polling");
    });
});

describe("M6：SSE 服务端终结 → 探活定去留，不复活", () => {
    it("closed + 探活 404 → dropTask（行/live 清，rebalance 不重建 channel）", async () => {
        mocks.tasks.mockResolvedValue([
            snap("g1", "translating", 50),
            snap("g2", "translating", 40),
        ]);
        used.push("g1", "g2");
        mocks.snapshot.mockImplementation((id: string) =>
            id === "g1"
                ? Promise.reject(new ApiError(404, "gone"))
                : Promise.resolve(snap(id, "translating")),
        );
        await taskStore.refresh();
        expect(openedFor()).toEqual(["g1", "g2"]);

        handlersOf(0).transport?.("closed"); // g1 的 ES readyState=CLOSED
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.task("g1")).toBeUndefined();
        expect(taskStore.live("g1")).toBeUndefined();
        expect(openedFor()).toEqual(["g1", "g2"]); // 无复活——仍是两次

        // 后续 rebalance（新 watch 触发）也不得复活 g1
        used.push("g3");
        taskStore.watch("g3");
        expect(openedFor()).toEqual(["g1", "g2", "g3"]);
    });

    it("closed + 探活仍在跑 → 降级轮询（不复活 SSE）", async () => {
        mocks.tasks.mockResolvedValue([snap("a1", "translating", 50)]);
        used.push("a1");
        await taskStore.refresh();
        handlersOf(0).transport?.("closed");
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.live("a1")!.transport).toBe("polling");
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(1); // 未复活
        mocks.snapshot.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(mocks.snapshot.mock.calls.map((c) => c[0])).toEqual(["a1"]);
    });

    it("closed + 探活终态 → 收敛摘除（不再观测）", async () => {
        mocks.tasks.mockResolvedValue([snap("f1", "translating", 50)]);
        used.push("f1");
        await taskStore.refresh();
        mocks.snapshot.mockResolvedValue(snap("f1", "done"));
        handlersOf(0).transport?.("closed");
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.task("f1")!.status).toBe("done");
        mocks.snapshot.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
        expect(mocks.snapshot).not.toHaveBeenCalled(); // 摘除干净
    });

    it("主动 unwatch 触发的 close 不走探活（wanted 先摘）", async () => {
        mocks.tasks.mockResolvedValue([snap("s1", "translating", 50)]);
        used.push("s1");
        await taskStore.refresh();
        mocks.snapshot.mockClear();
        taskStore.unwatch("s1");
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
        expect(mocks.snapshot).not.toHaveBeenCalled();
    });
});

describe("resync 帧：重放缺口 → 清派生态 + 拉快照对齐", () => {
    it("resync 清空 chunk/chunkItems 并 refetch snapshot；SSE 不降轮询", async () => {
        mocks.tasks.mockResolvedValue([snap("r1", "translating", 50)]);
        used.push("r1");
        await taskStore.refresh();
        const h = handlersOf(0);
        h.chunk?.({
            total: 5,
            done: 4,
            cached: 0,
            failed: 0,
            items: [{ seq: 3, status: "ok" }],
        });
        expect(taskStore.live("r1")!.chunkItems[3]?.status).toBe("ok");

        mocks.snapshot.mockClear();
        h.resync?.();
        expect(taskStore.live("r1")!.chunkItems).toEqual([]);
        expect(taskStore.live("r1")!.chunk).toBeUndefined();
        await vi.advanceTimersByTimeAsync(0);
        expect(mocks.snapshot.mock.calls.map((c) => c[0])).toEqual(["r1"]);
        // SSE 仍在——不标 polling、不重开 channel
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(1);
        expect(taskStore.live("r1")!.transport).not.toBe("polling");
    });

    it("resync 后探快照 404 → dropTask", async () => {
        mocks.tasks.mockResolvedValue([snap("r9", "translating", 50)]);
        used.push("r9");
        await taskStore.refresh();
        mocks.snapshot.mockRejectedValue(new ApiError(404, "gone"));
        handlersOf(0).resync?.();
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.task("r9")).toBeUndefined();
    });
});

describe("P2：chunk 帧按 seq 增量写（不再整组重建）", () => {
    it("携带项落位、空洞 pending、非法 seq 丢弃", async () => {
        mocks.tasks.mockResolvedValue([snap("k1", "translating", 50)]);
        used.push("k1");
        await taskStore.refresh();
        const h = handlersOf(0);
        h.chunk?.({
            total: 4,
            done: 2,
            cached: 0,
            failed: 1,
            items: [
                { seq: 1, status: "ok" },
                { seq: 3, status: "failed" },
                { seq: 99, status: "ok" }, // 越界——丢
            ],
        });
        const items = taskStore.live("k1")!.chunkItems;
        expect(items).toHaveLength(4);
        expect(items.map((i) => i.status)).toEqual([
            "pending",
            "ok",
            "pending",
            "failed",
        ]);

        // 第二帧只带变化段——只动该格
        h.chunk?.({
            total: 4,
            done: 3,
            cached: 1,
            failed: 1,
            items: [{ seq: 1, status: "cached" }],
        });
        expect(taskStore.live("k1")!.chunkItems.map((i) => i.status)).toEqual([
            "pending",
            "cached",
            "pending",
            "failed",
        ]);
    });
});
