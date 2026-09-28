// citations —— destPointOf 落点解析（fit 型 y/x 槽位）+
// extractBibAtDest 借道 destPointOf 的回归烟测。
import { describe, expect, it } from "vitest";
import {
    destPointOf,
    extractBibAtDest,
    type PdfDocLike,
} from "../reader/cite/citations";

const ref = { num: 7, gen: 0 };

describe("destPointOf", () => {
    it("XYZ：[ref,XYZ,left,top,zoom] → x=left y=top", () => {
        expect(destPointOf([ref, { name: "XYZ" }, 42, 700, null])).toEqual({
            ref,
            x: 42,
            y: 700,
        });
        // null-top：y 诚实缺席（整页锚近义），x 仍在
        expect(destPointOf([ref, { name: "XYZ" }, 42, null, 1])).toEqual({
            ref,
            x: 42,
            y: null,
        });
    });
    it("FitH/FitBH：[ref,fit,top] → y=top x=null", () => {
        expect(destPointOf([ref, { name: "FitH" }, 655])).toEqual({
            ref,
            x: null,
            y: 655,
        });
        expect(destPointOf([ref, { name: "FitBH" }, 640.5])).toEqual({
            ref,
            x: null,
            y: 640.5,
        });
    });
    it("FitR：[ref,fit,l,b,r,t] → y=top（5 号槽；4 号是 right 横坐标）", () => {
        expect(destPointOf([ref, { name: "FitR" }, 50, 100, 540, 700])).toEqual(
            { ref, x: null, y: 700 },
        );
    });
    it("整页型 Fit/FitV/FitB 与畸形输入 → y=null / null", () => {
        expect(destPointOf([ref, { name: "Fit" }])).toEqual({
            ref,
            x: null,
            y: null,
        });
        expect(destPointOf(null)).toBeNull();
        expect(destPointOf([])).toBeNull();
        expect(destPointOf([ref])).toBeNull();
        // NaN 防御——非数槽位归 null 不外吐
        expect(destPointOf([ref, { name: "FitH" }, "x"])).toEqual({
            ref,
            x: null,
            y: null,
        });
    });
});

describe("extractBibAtDest —— destPointOf 借道烟测", () => {
    const fakeDoc = (items: { str: string; x: number; y: number }[]) =>
        ({
            getDestination: async () => [ref, { name: "FitH" }, 700],
            getPageIndex: async () => 0,
            getPage: async () => ({
                getViewport: () => ({ height: 800, width: 600 }),
                getTextContent: async () => ({
                    // pdf.js transform[4]=x [5]=top-origin y——
                    // 测试数据给 bottom-up y，换回 f=800-y
                    items: items.map((it) => ({
                        str: it.str,
                        transform: [1, 0, 0, 1, it.x, 800 - it.y],
                    })),
                }),
            }),
        }) as unknown as PdfDocLike;

    it("FitH 落点行起向下收条目", async () => {
        const doc = fakeDoc([
            { str: "[1] Smith, J. Title of the work.", x: 60, y: 700 },
            { str: "Journal, 2024.", x: 78, y: 686 },
            { str: "[2] Next entry starts here.", x: 60, y: 660 },
        ]);
        const hit = await extractBibAtDest(doc, "cite.smith");
        expect(hit?.text).toContain("Smith");
        expect(hit?.text).toContain("Journal");
        expect(hit?.text).not.toContain("Next entry");
    });
    it("dest 缺失/畸形 → null", async () => {
        const doc = {
            getDestination: async () => null,
        } as unknown as PdfDocLike;
        expect(await extractBibAtDest(doc, "cite.x")).toBeNull();
    });
});
