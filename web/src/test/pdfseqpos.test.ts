// pdfseqpos —— seqpos 消费面单测：seqPos 侧键/缺位、seqPairs 双侧
// 齐全闸、nearestSeq 同页分位优先与跨页页沿排序。
import { describe, expect, it } from "vitest";
import { nearestSeq, seqPairs, seqPos } from "../reader/pdfseqpos";

const MAP = {
    "3": {
        o: { page: 1, fraction: 0.5 },
        t: { page: 1, fraction: 0.6 },
    },
    "7": {
        o: { page: 2, fraction: 0.1 },
        t: { page: 3, fraction: 0.2 },
    },
    "9": { o: { page: 5, fraction: 0.4 } }, // 单侧缺位——seqPairs 不收
};

describe("seqPos", () => {
    it("侧键：en→o zh→t；无 seq/单侧缺位 → null", () => {
        expect(seqPos(MAP, 3, "en")).toEqual({ page: 1, fraction: 0.5 });
        expect(seqPos(MAP, 3, "zh")).toEqual({ page: 1, fraction: 0.6 });
        expect(seqPos(MAP, 9, "zh")).toBeNull();
        expect(seqPos(MAP, 99, "en")).toBeNull();
    });
});

describe("seqPairs", () => {
    it("双侧齐全才出对；id 前缀 s", () => {
        const pairs = seqPairs(MAP);
        expect(pairs).toHaveLength(2);
        expect(pairs[0]).toEqual({
            id: "s3",
            original: { page: 1, fraction: 0.5 },
            translated: { page: 1, fraction: 0.6 },
        });
        expect(pairs.map((p) => p.id)).toEqual(["s3", "s7"]);
    });
    it("空 map → 空表", () => {
        expect(seqPairs({})).toEqual([]);
    });
});

describe("nearestSeq", () => {
    it("同页最近分位优先——跨页候选不抢", () => {
        // p1 frac0.55：seq3 同页差 0.05 vs seq7 跨页——同页恒胜
        expect(
            nearestSeq(MAP, "en", { page: 1, fraction: 0.55 }),
        ).toBe(3);
        // zh 侧同形（t 键取）
        expect(
            nearestSeq(MAP, "zh", { page: 1, fraction: 0.55 }),
        ).toBe(3);
    });
    it("跨页按页差+页沿排序", () => {
        // p4：seq7(p3) 差 1 页 vs seq9-o(p5) zh 侧缺席——seq7 唯一 zh 候选
        expect(
            nearestSeq(MAP, "zh", { page: 4, fraction: 0.5 }),
        ).toBe(7);
        // en 侧 seq9(p5) 页差 1 胜 seq7(p2) 页差 2——页差主导排序
        expect(
            nearestSeq(MAP, "en", { page: 4, fraction: 0.5 }),
        ).toBe(9);
        // 页差相同时页沿分位决胜：pos p2.5——seq3(p1 差1+0.5)=1.5
        // vs seq7(p2 同页差0.4)=0.4——同页优先
        expect(
            nearestSeq(MAP, "en", { page: 2, fraction: 0.5 }),
        ).toBe(7);
    });
    it("空 map / 该侧全缺 → null", () => {
        expect(nearestSeq({}, "en", { page: 1, fraction: 0 })).toBeNull();
        expect(
            nearestSeq({ "9": { o: { page: 1, fraction: 0 } } }, "zh", {
                page: 1,
                fraction: 0,
            }),
        ).toBeNull();
    });
});
