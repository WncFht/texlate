// pdfseqpos —— seqpos 消费面单测：seqPos 侧键/缺位、seqPairs 双侧
// 齐全闸、seqLands 阅读序排序、containingSeq 含点块 floor 语义
// （双栏 col 分流、无 x 投影降级、距离闸 null）。
import { describe, expect, it } from "vitest";
import {
    containingSeq,
    seqLands,
    seqPairs,
    seqPos,
} from "../reader/pdfseqpos";

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

// 双栏地标：页1 左栏 seq1(.1)/seq2(.5)、右栏 seq3(.1)/seq4(.6)、
// 页2 seq5——阅读序 (page,col,fraction) → [1,2,3,4,5]
const COLMAP = {
    "1": { o: { page: 1, fraction: 0.1, x: 0.1 } },
    "2": { o: { page: 1, fraction: 0.5, x: 0.1 } },
    "3": { o: { page: 1, fraction: 0.1, x: 0.6 } },
    "4": { o: { page: 1, fraction: 0.6, x: 0.6 } },
    "5": { o: { page: 2, fraction: 0.2, x: 0.15 } },
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

describe("seqLands", () => {
    it("带 Pos 的 seq 按 (page,col,fraction) 升序", () => {
        expect(seqLands(COLMAP, "en").map((l) => l.seq)).toEqual([
            1, 2, 3, 4, 5,
        ]);
        // zh 侧全缺 → 空表
        expect(seqLands(COLMAP, "zh")).toEqual([]);
    });
});

describe("containingSeq", () => {
    it("floor 含点块——不取最近邻", () => {
        // 右栏 frac.55 在 seq3 块内（.1–.6）；最近邻是 seq4(.6) 但
        // 锚记块首——点击落块内即归该块
        expect(
            containingSeq(COLMAP, "en", {
                page: 1,
                fraction: 0.55,
                x: 0.7,
            }),
        ).toBe(3);
        // 同页同栏 seq4 块内
        expect(
            containingSeq(COLMAP, "en", {
                page: 1,
                fraction: 0.9,
                x: 0.7,
            }),
        ).toBe(4);
    });
    it("栏分流：右栏顶部点击归左栏末块（跨栏续段）", () => {
        // (1,col1,.05) 在右栏首锚 seq3(.1) 之前——阅读序上仍晚于
        // 全部左栏锚，floor = seq2（左栏末块延伸到右栏顶部）
        expect(
            containingSeq(COLMAP, "en", {
                page: 1,
                fraction: 0.05,
                x: 0.7,
            }),
        ).toBe(2);
        // 左栏内正常 floor
        expect(
            containingSeq(COLMAP, "en", {
                page: 1,
                fraction: 0.3,
                x: 0.1,
            }),
        ).toBe(1);
    });
    it("无 x 退化投影 floor——栏不可判仍取 (page,frac) 最大不超者", () => {
        // (1,.55) 无 x：投影 ≤ 的有 seq1(.1)/seq2(.5)/seq3(.1)，
        // 最大者 seq2——与带 x 路径（seq3）口径不同是有意降级
        expect(
            containingSeq(COLMAP, "en", { page: 1, fraction: 0.55 }),
        ).toBe(2);
    });
    it("早于全部地标：≤1 页收首锚，>1 页 null", () => {
        // (1,col0,.05) 早于首锚 (1,col0,.1) 0.05 页 → 收 seq1
        expect(
            containingSeq(COLMAP, "en", {
                page: 1,
                fraction: 0.05,
                x: 0.05,
            }),
        ).toBe(1);
        // 首锚在 p3 的稀疏图：点击 p1 差 2.2 页 → null
        const LATE = { "8": { o: { page: 3, fraction: 0.2, x: 0.1 } } };
        expect(
            containingSeq(LATE, "en", { page: 1, fraction: 0, x: 0.1 }),
        ).toBeNull();
        // 无 x 同闸
        expect(
            containingSeq(LATE, "en", { page: 1, fraction: 0 }),
        ).toBeNull();
    });
    it("floor 距离闸：线性距 >1.2 页 → null（稀疏 seqpos 落旧路）", () => {
        // 点击 p5：floor 是 seq5(p2.2)，距 3.3 页 → 拒
        expect(
            containingSeq(COLMAP, "en", {
                page: 5,
                fraction: 0.5,
                x: 0.1,
            }),
        ).toBeNull();
        // p2 块内距 seq5 锚 0.6 页 → 收
        expect(
            containingSeq(COLMAP, "en", {
                page: 2,
                fraction: 0.8,
                x: 0.1,
            }),
        ).toBe(5);
    });
    it("单栏页右半点击不被 col1 floor 吸到页底锚（N1 回归）", () => {
        // 全页锚皆 col0（单栏排版/右栏无锚）——pos.x>=0.45 须降级
        const SINGLE = {
            "1": { o: { page: 1, fraction: 0.1, x: 0.1 } },
            "2": { o: { page: 1, fraction: 0.5, x: 0.1 } },
            "3": { o: { page: 1, fraction: 0.9, x: 0.1 } },
        };
        // 右半点击 frac .6：col0 floor = seq2(.5)；旧码 col1 floor
        // 会吸到页末 seq3
        expect(
            containingSeq(SINGLE, "en", { page: 1, fraction: 0.6, x: 0.7 }),
        ).toBe(2);
        expect(
            containingSeq(SINGLE, "en", { page: 1, fraction: 0.2, x: 0.7 }),
        ).toBe(1);
    });
    it("同行幅面 snap：宽行右半点击直命锚行，不被栏判错划", () => {
        // 通栏行（TOC/标题）：锚 x0=0.08 x1=0.95 跨双栏——raw-x=0.7
        // 会被栏判为 col1，floor 进而吸到 col0 末锚 seq6（阅读序合法
        // 但离点击行老远）；snap 依幅面包含直命 seq2
        const WIDE = {
            "1": { o: { page: 1, fraction: 0.3, x: 0.08, x1: 0.4 } },
            "2": { o: { page: 1, fraction: 0.5, x: 0.08, x1: 0.95 } }, // 通栏行
            "6": { o: { page: 1, fraction: 0.7, x: 0.08, x1: 0.4 } }, // col0 末锚
            "3": { o: { page: 1, fraction: 0.6, x: 0.55, x1: 0.9 } }, // 右栏锚
        };
        // 点击宽行右半：锚 fraction=行顶、点击=行内 → d≈+0.008
        expect(
            containingSeq(WIDE, "en", { page: 1, fraction: 0.508, x: 0.7 }),
        ).toBe(2);
        // 点击在锚行顶之上（d=-0.01 < -_ROW_UP）→ 非本行走 floor：
        // col1 点击早于 seq3 → 跨栏续段归 col0 末锚 seq6
        expect(
            containingSeq(WIDE, "en", { page: 1, fraction: 0.49, x: 0.7 }),
        ).toBe(6);
    });
    it("同行多格（表头）→ 取 x0≤点击的最右格段", () => {
        // 表头同行：seq10 通幅锚 + seq11 右格锚——点击 x=0.6 同时落在
        // 两者 [x0,x1] 内且 d 相同；min-d 先见者得 seq10，rightmost-x0
        // 打破取 seq11（点击所在格段）
        const HDR = {
            "9": { o: { page: 1, fraction: 0.3, x: 0.08, x1: 0.4 } },
            "10": { o: { page: 1, fraction: 0.5, x: 0.08, x1: 0.95 } },
            "11": { o: { page: 1, fraction: 0.5, x: 0.5, x1: 0.95 } },
            "12": { o: { page: 1, fraction: 0.6, x: 0.08, x1: 0.4 } },
        };
        expect(
            containingSeq(HDR, "en", { page: 1, fraction: 0.508, x: 0.6 }),
        ).toBe(11);
        expect(
            containingSeq(HDR, "en", { page: 1, fraction: 0.508, x: 0.3 }),
        ).toBe(10);
    });
    it("空 map / 该侧全缺 → null", () => {
        expect(
            containingSeq({}, "en", { page: 1, fraction: 0 }),
        ).toBeNull();
        expect(
            containingSeq(
                { "9": { o: { page: 1, fraction: 0 } } },
                "zh",
                { page: 1, fraction: 0 },
            ),
        ).toBeNull();
    });
});
