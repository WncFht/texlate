// taskStore SSE 窗口：MAX_SSE_TASKS 上限内 EventSource、溢出任务降级
// snapshot 轮询；pin（reader 聚焦）抢占；终态让位/摘除；resetLive 重订。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    snapshot: vi.fn(),
    deleteTask: vi.fn(),
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
            deleteTask: mocks.deleteTask,
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
import { MAX_SSE_TASKS, POLL_INTERVAL_MS, taskStore } from "../stores/tasks";

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

/** openTaskEvents 第 i 次调用拿到的 handlers */
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
    mocks.deleteTask.mockReset().mockResolvedValue(undefined);
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

describe("taskStore SSE 窗口（MAX_SSE_TASKS）", () => {
    it("refresh：非终态任务超窗口——前 N 个开 SSE，其余降级 snapshot 轮询", async () => {
        // updated_at 新→旧排序占槽
        mocks.tasks.mockResolvedValue([
            snap("w1", "translating", 50),
            snap("w2", "translating", 40),
            snap("w3", "translating", 30),
            snap("w4", "translating", 20),
            snap("w5", "translating", 10),
        ]);
        used.push("w1", "w2", "w3", "w4", "w5");
        await taskStore.refresh();

        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(MAX_SSE_TASKS);
        expect(openedFor()).toEqual(["w1", "w2", "w3"]);
        // 溢出两任务轮询（startPoll 首轮立即 tick）
        expect(mocks.snapshot.mock.calls.map((c) => c[0]).sort()).toEqual([
            "w4",
            "w5",
        ]);

        mocks.snapshot.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(mocks.snapshot.mock.calls.map((c) => c[0]).sort()).toEqual([
            "w4",
            "w5",
        ]);
    });

    it("watch（pin）抢占 SSE 槽：原槽尾降级为轮询", async () => {
        mocks.tasks.mockResolvedValue([
            snap("p1", "translating", 50),
            snap("p2", "translating", 40),
            snap("p3", "translating", 30),
            snap("p4", "translating", 20),
        ]);
        used.push("p1", "p2", "p3", "p4");
        await taskStore.refresh();
        expect(openedFor()).toEqual(["p1", "p2", "p3"]);

        mocks.snapshot.mockClear(); // 清掉 refresh 阶段 p4 的首轮 tick
        taskStore.watch("p4"); // reader 聚焦——pin 最优先
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(4);
        expect(openedFor().at(-1)).toBe("p4");
        expect(channelOf(2).close).toHaveBeenCalled(); // p3 被挤下 SSE
        await vi.advanceTimersByTimeAsync(0);
        expect(mocks.snapshot.mock.calls.map((c) => c[0]).sort()).toEqual([
            "p3",
        ]);
    });

    it("done 终态让位：腾出 SSE 槽给轮询任务；live 收敛释放 logs/stages", async () => {
        mocks.tasks.mockResolvedValue([
            snap("d1", "translating", 50),
            snap("d2", "translating", 40),
            snap("d3", "translating", 30),
            snap("d4", "translating", 20),
        ]);
        used.push("d1", "d2", "d3", "d4");
        await taskStore.refresh();
        expect(mocks.snapshot.mock.calls.map((c) => c[0])).toEqual(["d4"]);

        const h = handlersOf(0); // d1
        h.log?.({ line: "x" });
        h.stage?.({ stage: "translating", progress: 10, message: "", at: 0 });
        expect(taskStore.live("d1")!.logs).toHaveLength(1);
        expect(taskStore.live("d1")!.stages).toHaveLength(1);

        h.done?.({ status: "done", artifacts: {}, stats: { tokens: 5 } });

        expect(channelOf(0).close).toHaveBeenCalled();
        expect(taskStore.task("d1")!.status).toBe("done");
        const live = taskStore.live("d1")!;
        expect(live.done?.stats.tokens).toBe(5);
        expect(live.logs).toEqual([]); // 终态收敛释放
        expect(live.stages).toEqual([]);
        // d4 升格 SSE
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(4);
        expect(openedFor().at(-1)).toBe("d4");
    });

    it("轮询任务回终态 snapshot——摘除观测且不再轮询", async () => {
        mocks.tasks.mockResolvedValue([
            snap("q1", "translating", 50),
            snap("q2", "translating", 40),
            snap("q3", "translating", 30),
            snap("q4", "translating", 20),
        ]);
        used.push("q1", "q2", "q3", "q4");
        mocks.snapshot.mockImplementation((id: string) =>
            Promise.resolve(snap(id, id === "q4" ? "done" : "translating")),
        );
        await taskStore.refresh();
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.task("q4")!.status).toBe("done");

        mocks.snapshot.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
        expect(mocks.snapshot.mock.calls.map((c) => c[0])).toEqual([]); // q4 不再被轮询，且无新待轮任务
    });

    it("轮询 404——任务行已删：本地移除且停止观测", async () => {
        mocks.tasks.mockResolvedValue([
            snap("r1", "translating", 50),
            snap("r2", "translating", 40),
            snap("r3", "translating", 30),
            snap("r4", "translating", 20),
        ]);
        used.push("r1", "r2", "r3", "r4");
        mocks.snapshot.mockImplementation((id: string) =>
            id === "r4"
                ? Promise.reject(new ApiError(404, "gone"))
                : Promise.resolve(snap(id, "translating")),
        );
        await taskStore.refresh();
        await vi.advanceTimersByTimeAsync(0);
        expect(taskStore.task("r4")).toBeUndefined();
        expect(taskStore.live("r4")).toBeUndefined();
    });

    it("resetLive：关旧 channel 重订同 task_id（水位线保留在 client 层）", async () => {
        mocks.tasks.mockResolvedValue([snap("s1", "translating", 50)]);
        used.push("s1");
        await taskStore.refresh();
        expect(openedFor()).toEqual(["s1"]);

        taskStore.resetLive("s1");
        expect(channelOf(0).close).toHaveBeenCalled();
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(2);
        expect(openedFor().at(-1)).toBe("s1");
    });

    it("pin 超窗：watch 返回轮询句柄，close 即摘除观测", async () => {
        mocks.tasks.mockResolvedValue([]);
        used.push("x1", "x2", "x3", "x4");
        taskStore.watch("x1");
        taskStore.watch("x2");
        taskStore.watch("x3");
        const ch4 = taskStore.watch("x4"); // 第 4 个 pin——槽满，轮询态
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(3);
        expect(ch4.closed).toBe(false);
        ch4.close();
        expect(ch4.closed).toBe(true);
    });

    it("watch 幂等：重复调用复用同一 channel", async () => {
        mocks.tasks.mockResolvedValue([snap("m1", "translating", 50)]);
        used.push("m1");
        await taskStore.refresh();
        const a = taskStore.watch("m1");
        const b = taskStore.watch("m1");
        expect(a).toBe(b);
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(1);
    });

    it("refresh 旧读守卫：行 last_seq 落后于已消费 seq → 现行行不回退", async () => {
        mocks.tasks.mockResolvedValue([
            { ...snap("g1", "translating", 50), progress: 90, last_seq: 50 },
        ]);
        used.push("g1");
        await taskStore.refresh();
        expect(taskStore.task("g1")!.progress).toBe(90);

        // 列表读到更早快照（last_seq=30 < 行内 50）——status/progress 不回退
        mocks.tasks.mockResolvedValue([
            {
                ...snap("g1", "fetching", 10),
                progress: 40,
                last_seq: 30,
            },
        ]);
        await taskStore.refresh();
        expect(taskStore.task("g1")!.status).toBe("translating");
        expect(taskStore.task("g1")!.progress).toBe(90);

        // last_seq 推进的正常行照常合并
        mocks.tasks.mockResolvedValue([
            { ...snap("g1", "translating", 60), progress: 95, last_seq: 60 },
        ]);
        await taskStore.refresh();
        expect(taskStore.task("g1")!.progress).toBe(95);
    });
});
