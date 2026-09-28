import { describe, expect, it } from "vitest";
import {
    createPositionMapper,
    type Alignment,
} from "../reader/logic/alignment";

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
                {
                    id: "a",
                    original: { page: 1, fraction: 0 },
                    translated: { page: 1, fraction: 0 },
                },
                {
                    id: "b",
                    original: { page: 3, fraction: 0 },
                    translated: { page: 4, fraction: 0 },
                },
                {
                    id: "c",
                    original: { page: 4, fraction: 0 },
                    translated: { page: 6, fraction: 0 },
                },
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
        expect(map({ page: 4, fraction: 0.9 }, "original")).toMatchObject({
            page: 6,
        });
    });

    it("landmarks 反向：译文 → 原文 同样走 pairs 分段插值", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                {
                    id: "a",
                    original: { page: 1, fraction: 0 },
                    translated: { page: 1, fraction: 0 },
                },
                {
                    id: "b",
                    original: { page: 3, fraction: 0 },
                    translated: { page: 4, fraction: 0 },
                },
                {
                    id: "c",
                    original: { page: 4, fraction: 0 },
                    translated: { page: 6, fraction: 0 },
                },
            ],
        };
        const map = createPositionMapper(al, { original: 4, translated: 6 });
        // 译文 p4 顶（= pair b 锚点）→ 原文 p3 顶
        expect(map({ page: 4, fraction: 0 }, "translated")).toMatchObject({
            page: 3,
            fraction: 0,
        });
        // 译文 p2.5（a/b 段中点 x=1.5）→ 原文 p2 顶（y=1.0）
        const mid = map({ page: 2, fraction: 0.5 }, "translated");
        expect(mid.page).toBe(2);
        expect(mid.fraction).toBeCloseTo(0, 5);
        // 首对之前 clamp 到首对原文侧
        expect(map({ page: 1, fraction: 0 }, "translated")).toMatchObject({
            page: 1,
        });
        // 末对之后 clamp：译文 p6 → 原文 p4
        expect(map({ page: 6, fraction: 0.9 }, "translated")).toMatchObject({
            page: 4,
        });
    });

    it("regions 反向：译文 region 内位置映回原文 region 归一化坐标", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                {
                    original: { page: 1, fraction: 0 },
                    translated: { page: 1, fraction: 0 },
                },
                {
                    original: { page: 4, fraction: 0 },
                    translated: { page: 6, fraction: 0 },
                },
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
        // 译文 region 中点 (p3,f0.6) → 原文 region 中点 (p2,f0.4)
        const out = map({ page: 3, fraction: 0.6 }, "translated");
        expect(out.page).toBe(2);
        expect(out.fraction).toBeCloseTo(0.4, 5);
        // region 端点：译文 p3 f0.8（区间尾）→ 原文 p2 f0.6
        const tail = map({ page: 3, fraction: 0.8 }, "translated");
        expect(tail.page).toBe(2);
        expect(tail.fraction).toBeCloseTo(0.6, 5);
    });

    it("regions 优先于 pairs：图浮动块内按归一化位置映射", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                {
                    original: { page: 1, fraction: 0 },
                    translated: { page: 1, fraction: 0 },
                },
                {
                    original: { page: 4, fraction: 0 },
                    translated: { page: 6, fraction: 0 },
                },
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
        const map = createPositionMapper(
            { kind: "pages", heights },
            { original: 4, translated: 6 },
        );
        expect(
            map({ page: 1, fraction: 0.1, viewport: 0.2 }, "original").viewport,
        ).toBe(0.2);
    });

    it("heights 缺失时按每页 1 计", () => {
        const map = createPositionMapper(
            {
                kind: "landmarks",
                pairs: [
                    {
                        original: { page: 1, fraction: 0 },
                        translated: { page: 1, fraction: 0 },
                    },
                    {
                        original: { page: 4, fraction: 0 },
                        translated: { page: 6, fraction: 0 },
                    },
                ],
            },
            { original: 4, translated: 6 },
        );
        const out = map({ page: 2, fraction: 0.5 }, "original"); // x=1.5 → y=2.5 → p3 f0.5
        expect(out.page).toBe(3);
        expect(out.fraction).toBeCloseTo(0.5, 5);
    });

    it("colAware：pairs 带 x → 阅读序线性化（右栏顶排在左栏底之后）", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                {
                    id: "a",
                    original: { page: 1, fraction: 0, x: 0.1 },
                    translated: { page: 1, fraction: 0, x: 0.1 },
                },
                {
                    id: "b",
                    original: { page: 2, fraction: 0.9, x: 0.1 },
                    translated: { page: 2, fraction: 0.9, x: 0.1 },
                },
                {
                    id: "c",
                    original: { page: 2, fraction: 0.1, x: 0.6 },
                    translated: { page: 2, fraction: 0.1, x: 0.6 },
                },
                {
                    id: "d",
                    original: { page: 3, fraction: 0, x: 0.1 },
                    translated: { page: 3, fraction: 0, x: 0.1 },
                },
            ],
        };
        const map = createPositionMapper(al, { original: 4, translated: 6 });
        // 右栏顶 (p2,.05,x.6)：阅读序位 1.525（左栏底 1.45 之后）——
        // 映回右栏顶；旧版 page+frac 线性位 1.05 会错落到 a/b 段
        const rt = map({ page: 2, fraction: 0.05, x: 0.6 }, "original");
        expect(rt.page).toBe(2);
        expect(rt.fraction).toBeCloseTo(0.05, 2);
        // 左栏底 (p2,.9,x.1) 映回左栏底，不穿栏
        const lb = map({ page: 2, fraction: 0.9, x: 0.1 }, "original");
        expect(lb.page).toBe(2);
        expect(lb.fraction).toBeCloseTo(0.9, 2);
    });

    it("dropOutliers：离群锚被剔——插值不被拽出 V 形", () => {
        const al: Alignment = {
            kind: "landmarks",
            heights,
            pairs: [
                {
                    id: "a",
                    original: { page: 1, fraction: 0 },
                    translated: { page: 1, fraction: 0 },
                },
                {
                    id: "b",
                    original: { page: 2, fraction: 0 },
                    translated: { page: 2, fraction: 0 },
                },
                // 假锚：原文 p3 错锚到译文 p6（邻锚期望 ~p3，偏 3 页 > 2 均页高）
                {
                    id: "bad",
                    original: { page: 3, fraction: 0 },
                    translated: { page: 6, fraction: 0 },
                },
                {
                    id: "c",
                    original: { page: 4, fraction: 0 },
                    translated: { page: 4, fraction: 0 },
                },
                {
                    id: "d",
                    original: { page: 5, fraction: 0 },
                    translated: { page: 5, fraction: 0 },
                },
            ],
        };
        const map = createPositionMapper(al, { original: 4, translated: 6 });
        // 原文 p3 顶剔除假锚后在 b/c 间插 → 译文 p3；不剔则落 p6
        expect(map({ page: 3, fraction: 0 }, "original")).toMatchObject({
            page: 3,
            fraction: 0,
        });
        // 反向同样剔：译文 p6 映回原文末段（d 锚 p5 后 clamp 域），不落到 p3 假锚
        const back = map({ page: 6, fraction: 0 }, "translated");
        expect(back.page).toBeGreaterThanOrEqual(4);
    });
});
