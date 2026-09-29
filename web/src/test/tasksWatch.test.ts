// taskStore SSE 窗口：MAX_SSE_TASKS 上限内 EventSource、溢出任务降级
// 共享列表轮询（pollListWanted 一拍 /api/tasks 归并，非逐任务 snapshot）；
// pin（reader 聚焦）抢占；终态让位/摘除；resetLive 重订。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    snapshot: vi.fn(),
    openTaskEvents: vi.fn(),
}));

// SSE 脚手架收敛到 _taskkit（同 liveFixes/liveFixloop 同构件）：clientModuleMock
// 把 openTaskEvents 分到顶层导出、其余键进 api 覆写
vi.mock("../api/client", async (importOriginal) => {
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

import { type TaskSnapshot } from "../api/client";
import { MAX_SSE_TASKS, POLL_INTERVAL_MS, taskStore } from "../stores/tasks";
import {
    channelOf,
    handlersOf,
    mkChannel,
    mkSnap,
    openedFor,
    trackWatches,
} from "./_taskkit";

// (id, status, updated) 签名 = mkSnap() 出厂形——updated 映 updated_at
// （0 回基线戳，done→100 其余→40 同口径）
const snap = mkSnap();

const used: string[] = [];
// afterEach 统一 unwatch used 桶（幂等）——注册见 _taskkit 头注
trackWatches(used, taskStore);

beforeEach(() => {
    vi.useFakeTimers();
    mocks.tasks.mockReset();
    mocks.snapshot
        .mockReset()
        .mockImplementation((id: string) =>
            Promise.resolve(snap(id, "translating")),
        );
    mocks.openTaskEvents.mockReset().mockImplementation(() => mkChannel());
});

afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe("taskStore SSE 窗口（MAX_SSE_TASKS）", () => {
    it("refresh：非终态任务超窗口——前 N 个开 SSE，其余降级共享列表轮询", async () => {
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
        expect(openedFor(mocks)).toEqual(["w1", "w2", "w3"]);
        // 溢出两任务由共享列表轮询覆盖——不再逐任务开 snapshot 轮询
        expect(mocks.snapshot).not.toHaveBeenCalled();
        // refresh 一拍 + 轮询器立补一拍
        expect(mocks.tasks.mock.calls.length).toBeGreaterThanOrEqual(2);

        mocks.tasks.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(mocks.tasks).toHaveBeenCalled();
        expect(mocks.snapshot).not.toHaveBeenCalled();
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
        expect(openedFor(mocks)).toEqual(["p1", "p2", "p3"]);

        taskStore.watch("p4"); // reader 聚焦——pin 最优先
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(4);
        expect(openedFor(mocks).at(-1)).toBe("p4");
        expect(channelOf(mocks, 2).close).toHaveBeenCalled(); // p3 被挤下 SSE
        // p3 非 pin——降级进共享列表轮询：下拍 /api/tasks 覆盖而非 snapshot
        mocks.tasks.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(mocks.tasks).toHaveBeenCalled();
        expect(mocks.snapshot).not.toHaveBeenCalled();
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
        // d4 由共享列表轮询覆盖（refresh 一拍 + 轮询补拍），无逐任务 snapshot
        expect(mocks.snapshot).not.toHaveBeenCalled();
        expect(mocks.tasks.mock.calls.length).toBeGreaterThanOrEqual(2);

        const h = handlersOf(mocks, 0); // d1
        h.log?.({ line: "x" });
        h.stage?.({ stage: "translating", progress: 10, message: "", at: 0 });
        expect(taskStore.live("d1")!.logs).toHaveLength(1);
        expect(taskStore.live("d1")!.stages).toHaveLength(1);

        h.done?.({ status: "done", artifacts: {}, stats: { tokens: 5 } });

        expect(channelOf(mocks, 0).close).toHaveBeenCalled();
        expect(taskStore.task("d1")!.status).toBe("done");
        const live = taskStore.live("d1")!;
        expect(live.done?.stats.tokens).toBe(5);
        expect(live.logs).toEqual([]); // 终态收敛释放
        expect(live.stages).toEqual([]);
        // d4 升格 SSE
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(4);
        expect(openedFor(mocks).at(-1)).toBe("d4");
    });

    it("轮询任务回终态——摘除观测且不再轮询", async () => {
        let q4status: TaskSnapshot["status"] = "translating";
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("q1", "translating", 50),
                snap("q2", "translating", 40),
                snap("q3", "translating", 30),
                snap("q4", q4status, 20),
            ]),
        );
        used.push("q1", "q2", "q3", "q4");
        await taskStore.refresh();

        q4status = "done";
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(taskStore.task("q4")!.status).toBe("done");

        mocks.tasks.mockClear();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);
        // q4 摘除、轮询集清空——共享定时器也随之停摆
        expect(mocks.tasks).not.toHaveBeenCalled();
    });

    it("轮询任务从列表消失——按已删收敛：本地移除且停止观测", async () => {
        const all = [
            snap("r1", "translating", 50),
            snap("r2", "translating", 40),
            snap("r3", "translating", 30),
            snap("r4", "translating", 20),
        ];
        mocks.tasks.mockImplementation(() => Promise.resolve(all));
        used.push("r1", "r2", "r3", "r4");
        await taskStore.refresh();

        all.length = 3; // r4 从 tenant 列表消失 = 已删（与轮询 404 同收敛）
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(taskStore.task("r4")).toBeUndefined();
        expect(taskStore.live("r4")).toBeUndefined();
    });

    it("resetLive：关旧 channel 重订同 task_id（水位线保留在 client 层）", async () => {
        mocks.tasks.mockResolvedValue([snap("s1", "translating", 50)]);
        used.push("s1");
        await taskStore.refresh();
        expect(openedFor(mocks)).toEqual(["s1"]);

        taskStore.resetLive("s1");
        expect(channelOf(mocks, 0).close).toHaveBeenCalled();
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(2);
        expect(openedFor(mocks).at(-1)).toBe("s1");
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

describe("taskStore ensureFresh / patch", () => {
    it("ensureFresh：TTL 内二次调用不重拉；过期再拉", async () => {
        mocks.tasks.mockResolvedValue([]); // 空列表——无 wanted 无轮询器
        await taskStore.ensureFresh(60_000);
        await taskStore.ensureFresh(60_000);
        expect(mocks.tasks).toHaveBeenCalledTimes(1); // TTL 门内幂等

        // 假时钟推进越过 TTL（Date.now 随钟走）——第三调用再发请求
        await vi.advanceTimersByTimeAsync(61_000);
        await taskStore.ensureFresh(60_000);
        expect(mocks.tasks).toHaveBeenCalledTimes(2);
    });

    it("patch：undefined 键跳过不清值；行引用不变；未知 id 空转", async () => {
        mocks.tasks.mockResolvedValue([snap("pt1", "translating", 50)]);
        used.push("pt1");
        await taskStore.refresh();
        const row = taskStore.task("pt1")!;

        taskStore.patch("pt1", { progress: 77, message: "m1" });
        expect(row.progress).toBe(77);
        expect(row.message).toBe("m1");
        // undefined 值跳过而非清字段——patch 只带要改的键
        taskStore.patch("pt1", { message: undefined });
        expect(row.message).toBe("m1");
        // 字段级写——行对象引用保持（M9：<For> 不整行重挂）
        expect(taskStore.task("pt1")).toBe(row);

        taskStore.patch("ghost", { progress: 1 }); // 未知 id——空转不抛
        expect(taskStore.task("ghost")).toBeUndefined();
        expect(taskStore.state.tasks).toHaveLength(1);
    });
});
