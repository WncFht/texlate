// @vitest-environment jsdom
// chunkPoll 增量/回退路直测（liveReading 经 LivePane 只盖住整窗道）：
//  - 脏 seq 定点拉：未见/status 翻转的 seq 走 taskChunksSeqs(?seqs=)
//  - 零脏拍零请求（不发请求也不重分发）
//  - 响应缺席的脏 seq 按已见记账——不永动重拉同一批
//  - transport!=live / chunkItems 空 → taskChunks 整窗回退
//  - 缓存页同步回放给迟到订阅者；末订阅者退订停拍
//  - pollChunksOnce 强拉整窗（冻结收尾补拍）

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    taskChunks: vi.fn(),
    taskChunksSeqs: vi.fn(),
    live: vi.fn(),
}));

vi.mock("../api/client", () => ({
    api: {
        taskChunks: mocks.taskChunks,
        taskChunksSeqs: mocks.taskChunksSeqs,
    },
}));

vi.mock("../stores/tasks", () => ({
    taskStore: { live: mocks.live },
}));

import {
    CHUNK_WINDOW,
    pollChunksOnce,
    subscribeChunks,
} from "../reader/logic/chunkPoll";
import type { TaskChunkRow, TaskChunksPage } from "../api/client";

const row = (seq: number, status: string, zh = ""): TaskChunkRow => ({
    seq,
    kind: "p",
    status,
    en: `en${seq}`,
    zh,
});

const page = (
    chunks: TaskChunkRow[],
    total = chunks.length,
): TaskChunksPage => ({
    chunks,
    total,
});

/** taskStore.live 返回的可变活态——测试体改字段驱动下一拍判定 */
const liveState: {
    transport: string;
    chunkItems: { seq: number; status: string }[];
} = { transport: "live", chunkItems: [] };

let taskId = "";
let serial = 0;
const unsubs: (() => void)[] = [];

const subscribe = (cb = vi.fn()) => {
    unsubs.push(subscribeChunks(taskId, cb));
    return cb;
};

/** tick 内 await 的是已决 promise——微任务冲刷即可（假时钟不吃微任务） */
const flush = async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
};

const lastPage = (cb: ReturnType<typeof vi.fn>) =>
    cb.mock.calls.at(-1)![0] as TaskChunksPage;

beforeEach(() => {
    vi.useFakeTimers();
    taskId = `t_${++serial}`;
    liveState.transport = "live";
    liveState.chunkItems = [];
    mocks.live.mockReset().mockImplementation(() => liveState);
    mocks.taskChunks.mockReset().mockResolvedValue(page([]));
    mocks.taskChunksSeqs.mockReset().mockResolvedValue(page([]));
});

afterEach(async () => {
    for (const u of unsubs.splice(0)) u();
    await flush();
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe("chunkPoll 增量道", () => {
    it("首拍：未见 seq 全脏 → ?seqs= 定点拉取并按序分发", async () => {
        liveState.chunkItems = [
            { seq: 0, status: "ok" },
            { seq: 1, status: "pending" },
            { seq: 2, status: "ok" },
        ];
        mocks.taskChunksSeqs.mockResolvedValue(
            page([row(0, "ok"), row(1, "pending"), row(2, "ok", "丙")]),
        );
        const cb = subscribe();
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);
        expect(mocks.taskChunksSeqs).toHaveBeenCalledWith(taskId, [0, 1, 2]);
        expect(mocks.taskChunks).not.toHaveBeenCalled();
        expect(cb).toHaveBeenCalledTimes(1);
        expect(lastPage(cb).chunks.map((r) => r.seq)).toEqual([0, 1, 2]);
    });

    it("零脏拍零请求；status 翻转只拉脏 seq、缓存合并分发", async () => {
        liveState.chunkItems = [
            { seq: 0, status: "ok" },
            { seq: 1, status: "pending" },
        ];
        mocks.taskChunksSeqs.mockResolvedValue(
            page([row(0, "ok"), row(1, "pending")]),
        );
        const cb = subscribe();
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);

        // 状态无变化 → 整拍零请求、不重分发
        await vi.advanceTimersByTimeAsync(2500);
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);
        expect(mocks.taskChunks).not.toHaveBeenCalled();
        expect(cb).toHaveBeenCalledTimes(1);

        // seq1 翻 ok → 只定点拉 seq1；分发页是全量缓存视图
        liveState.chunkItems = [
            { seq: 0, status: "ok" },
            { seq: 1, status: "ok" },
        ];
        mocks.taskChunksSeqs.mockResolvedValue(page([row(1, "ok", "乙")]));
        await vi.advanceTimersByTimeAsync(2500);
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(2);
        expect(mocks.taskChunksSeqs).toHaveBeenLastCalledWith(taskId, [1]);
        const out = lastPage(cb);
        expect(out.chunks.map((r) => r.seq)).toEqual([0, 1]);
        expect(out.chunks[1].zh).toBe("乙");
    });

    it("响应缺席的脏 seq 记 seen——不永动重拉同一批缺席行", async () => {
        liveState.chunkItems = [{ seq: 5, status: "ok" }];
        mocks.taskChunksSeqs.mockResolvedValue(page([], 3)); // 服务端无 seq5 行
        subscribe();
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);
        expect(mocks.taskChunksSeqs).toHaveBeenCalledWith(taskId, [5]);
        // 缺席 seq 不记 seen 时每拍都判脏——修复后两拍内零新增请求
        await vi.advanceTimersByTimeAsync(5000);
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);
    });

    it("缺席行后补自愈：status 再翻 → 重新判脏拉到行", async () => {
        liveState.chunkItems = [{ seq: 5, status: "pending" }];
        mocks.taskChunksSeqs.mockResolvedValue(page([], 3));
        subscribe();
        await flush();
        // 翻 ok → 重新判脏，这次行在
        liveState.chunkItems = [{ seq: 5, status: "ok" }];
        mocks.taskChunksSeqs.mockResolvedValue(page([row(5, "ok", "戊")]));
        await vi.advanceTimersByTimeAsync(2500);
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenLastCalledWith(taskId, [5]);
    });
});

describe("chunkPoll 整窗回退 + 订阅管理", () => {
    it("transport!=live → taskChunks 整窗回退（SSE 降级保正确性）", async () => {
        liveState.transport = "polling";
        liveState.chunkItems = [{ seq: 0, status: "ok" }];
        mocks.taskChunks.mockResolvedValue(page([row(0, "ok", "甲")], 1));
        const cb = subscribe();
        await flush();
        expect(mocks.taskChunks).toHaveBeenCalledTimes(1);
        expect(mocks.taskChunks).toHaveBeenCalledWith(taskId, 0, CHUNK_WINDOW);
        expect(mocks.taskChunksSeqs).not.toHaveBeenCalled();
        expect(lastPage(cb).chunks).toHaveLength(1);
    });

    it("live 但 chunkItems 空 → 仍整窗回退", async () => {
        liveState.transport = "live";
        liveState.chunkItems = [];
        mocks.taskChunks.mockResolvedValue(page([row(0, "ok")], 1));
        subscribe();
        await flush();
        expect(mocks.taskChunks).toHaveBeenCalledTimes(1);
        expect(mocks.taskChunksSeqs).not.toHaveBeenCalled();
    });

    it("缓存页同步回放给迟到订阅者（不等多一拍）", async () => {
        liveState.chunkItems = [{ seq: 0, status: "ok" }];
        mocks.taskChunksSeqs.mockResolvedValue(page([row(0, "ok", "甲")]));
        subscribe();
        await flush();
        const late = subscribe();
        expect(late).toHaveBeenCalledTimes(1);
        expect(lastPage(late).chunks.map((r) => r.seq)).toEqual([0]);
    });

    it("末订阅者退订 → 轮询器停拍", async () => {
        liveState.chunkItems = [{ seq: 0, status: "ok" }];
        mocks.taskChunksSeqs.mockResolvedValue(page([row(0, "ok")]));
        const unsub = subscribeChunks(taskId, vi.fn());
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);
        unsub();
        await vi.advanceTimersByTimeAsync(7500);
        await flush();
        expect(mocks.taskChunksSeqs).toHaveBeenCalledTimes(1);
    });

    it("pollChunksOnce 强拉整窗并分发（冻结收尾补拍）", async () => {
        liveState.chunkItems = [{ seq: 0, status: "ok" }];
        mocks.taskChunksSeqs.mockResolvedValue(page([row(0, "ok")]));
        const cb = subscribe();
        await flush();
        mocks.taskChunks.mockResolvedValue(page([row(0, "ok", "甲")], 1));
        await pollChunksOnce(taskId);
        await flush();
        expect(mocks.taskChunks).toHaveBeenCalledTimes(1);
        expect(cb).toHaveBeenCalledTimes(2);
        expect(lastPage(cb).chunks[0].zh).toBe("甲");
    });
});
