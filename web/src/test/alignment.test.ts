import { describe, expect, it } from "vitest";
import { createPositionMapper, type Alignment } from "../reader/alignment";

const heights = { original: [1, 1, 1, 1], translated: [1, 1, 1, 1, 1, 1] };

describe("createPositionMapper", () => {
    it("kind=pages 无 pairs → 同页码同 fraction，超界截断", () => {
        const map = createPositionMapper(
            { kind: "pages", heights },
            { original: 4, translated: 6 },
        );
        expect(map({ page: 2, fraction: 0.5 }, "original")).toEqual({
            page: 2,
            fraction: 0.5,
        });
        // 原文 4 页 → 译文 6 页方向不截断；反向 6→4 截断到 4
        expect(map({ page: 6, fraction: 0.9 }, "translated")).toEqual({
            page: 4,
            fraction: 0.9,
        });
    });

    it("landmarks：pairs 分段线性插值（页码偏移）", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                { id: "a", original: { page: 1, fraction: 0 }, translated: { page: 1, fraction: 0 } },
                { id: "b", original: { page: 3, fraction: 0 }, translated: { page: 4, fraction: 0 } },
                { id: "c", original: { page: 4, fraction: 0 }, translated: { page: 6, fraction: 0 } },
            ],
        };
        const map = createPositionMapper(al, { original: 4, translated: 6 });
        // 原文 p3 顶 → 译文 p4 顶
        expect(map({ page: 3, fraction: 0 }, "original")).toMatchObject({
            page: 4,
            fraction: 0,
        });
        // 原文 p2 顶 = pairs a/b 中点 → 译文 p2.5 顶
        const mid = map({ page: 2, fraction: 0 }, "original");
        expect(mid.page).toBe(2);
        expect(mid.fraction).toBeCloseTo(0.5, 5);
        // 首对之前 clamp 到首对
        expect(map({ page: 1, fraction: 0 }, "original").page).toBe(1);
        // 末对之后 clamp
        expect(map({ page: 4, fraction: 0.9 }, "original")).toMatchObject({ page: 6 });
    });

    it("regions 优先于 pairs：图浮动块内按归一化位置映射", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                { original: { page: 1, fraction: 0 }, translated: { page: 1, fraction: 0 } },
                { original: { page: 4, fraction: 0 }, translated: { page: 6, fraction: 0 } },
            ],
            regions: [
                {
                    id: "figure.1",
                    original: { page: 2, start: 0.2, end: 0.6 },
                    translated: { page: 3, start: 0.4, end: 0.8 },
                },
            ],
        };
        const map = createPositionMapper(al, { original: 4, translated: 6 });
        // 原文 region 中点 (p2,f0.4) → 译文 region 中点 (p3,f0.6)
        const out = map({ page: 2, fraction: 0.4 }, "original");
        expect(out.page).toBe(3);
        expect(out.fraction).toBeCloseTo(0.6, 5);
    });

    it("viewport 字段透传", () => {
        const map = createPositionMapper({ kind: "pages", heights }, { original: 4, translated: 6 });
        expect(map({ page: 1, fraction: 0.1, viewport: 0.2 }, "original").viewport).toBe(0.2);
    });

    it("heights 缺失时按每页 1 计", () => {
        const map = createPositionMapper(
            {
                kind: "landmarks",
                pairs: [
                    { original: { page: 1, fraction: 0 }, translated: { page: 1, fraction: 0 } },
                    { original: { page: 4, fraction: 0 }, translated: { page: 6, fraction: 0 } },
                ],
            },
            { original: 4, translated: 6 },
        );
        const out = map({ page: 2, fraction: 0.5 }, "original"); // x=1.5 → y=2.5 → p3 f0.5
        expect(out.page).toBe(3);
        expect(out.fraction).toBeCloseTo(0.5, 5);
    });
});
