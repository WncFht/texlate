import { describe, expect, it } from "vitest";
import { mergeChunkItems } from "../stores/liveFrames";
import type { ChunkItem } from "../api/client";

const it_ = (seq: number, status = "ok"): ChunkItem => ({ seq, status });

describe("mergeChunkItems（SSE 增量帧 → dense 累积数组）", () => {
    it("增量帧按 seq 覆盖合并，不动未携带的段", () => {
        const prev = [it_(0), it_(1), it_(2)];
        const next = mergeChunkItems(prev, [it_(1, "failed")]);
        expect(next).toEqual([it_(0), it_(1, "failed"), it_(2)]);
        expect(prev[1].status).toBe("ok"); // 不改原数组
    });

    it("首帧 seq 跳段 → 空洞补 pending 占位，保持 dense", () => {
        const next = mergeChunkItems([], [it_(3)]);
        expect(next).toHaveLength(4);
        expect(next[3]).toEqual(it_(3));
        expect(next.slice(0, 3).every((c) => c.status === "pending")).toBe(
            true,
        );
        expect(next[0].seq).toBe(0);
    });

    it("乱序到达：后到的低 seq 回填空洞", () => {
        let cur = mergeChunkItems([], [it_(5)]);
        cur = mergeChunkItems(cur, [it_(2, "cached"), it_(4, "failed")]);
        expect(cur).toHaveLength(6);
        expect(cur[2].status).toBe("cached");
        expect(cur[4].status).toBe("failed");
        expect(cur[3].status).toBe("pending");
    });

    it("重复 seq 以新帧为准（failed → ok 翻转）", () => {
        const prev = [it_(0, "failed"), it_(1)];
        const next = mergeChunkItems(prev, [it_(0)]);
        expect(next[0].status).toBe("ok");
    });

    it("非法 seq（负数/非整数）丢弃", () => {
        const next = mergeChunkItems(
            [it_(0)],
            [
                { seq: -1, status: "failed" },
                { seq: 1.5, status: "failed" },
            ],
        );
        expect(next).toEqual([it_(0)]);
    });

    it("病态超大 seq 丢弃——防填洞 OOM", () => {
        const next = mergeChunkItems([it_(0)], [{ seq: 1e9, status: "ok" }]);
        expect(next).toEqual([it_(0)]);
    });

    it("limit=e.total 约束：seq>total 越界丢弃（0/1 基两约定同界）", () => {
        expect(mergeChunkItems([], [it_(3)], 2)).toEqual([]);
        // 1 基 doc 管线：seq==total 合法
        const one = mergeChunkItems([], [it_(1), it_(2)], 2);
        expect(one).toHaveLength(3);
        expect(one[2].status).toBe("ok");
        // 0 基管线：seq==total-1 合法
        expect(mergeChunkItems([], [it_(2)], 3)).toHaveLength(3);
    });

    it("空 delta 返回等价数组", () => {
        const prev = [it_(0), it_(1)];
        expect(mergeChunkItems(prev, [])).toEqual(prev);
    });

    // doc 管线（worker._run_doc on_result）seq 从 1 起：seq0 必须补 pending，
    // 棋盘格不得因缺 0 段而错位
    it("doc 管线 seq 从 1 起 → seq0 补 pending 占位", () => {
        const next = mergeChunkItems([], [it_(1), it_(2, "failed")]);
        expect(next).toHaveLength(3);
        expect(next[0]).toEqual({ seq: 0, status: "pending" });
        expect(next[1].status).toBe("ok");
        expect(next[2].status).toBe("failed");
    });
});
