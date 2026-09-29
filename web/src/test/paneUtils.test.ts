import { describe, expect, it } from "vitest";
import {
    annotFileName,
    FIND_STATE,
    findCountText,
    fmtDate,
    outlineColor,
    pageSizeText,
    zoomToFontPx,
} from "../reader/logic/paneUtils";

describe("findCountText", () => {
    const NONE = "无匹配";

    it("notFound → noneLabel", () => {
        expect(
            findCountText(FIND_STATE.notFound, { current: 0, total: 0 }, NONE),
        ).toBe(NONE);
        // 即使 count 陈旧，notFound 优先
        expect(
            findCountText(FIND_STATE.notFound, { current: 3, total: 9 }, NONE),
        ).toBe(NONE);
    });

    it("有匹配 → current/total", () => {
        expect(
            findCountText(FIND_STATE.found, { current: 3, total: 12 }, NONE),
        ).toBe("3/12");
        expect(
            findCountText(FIND_STATE.wrapped, { current: 1, total: 12 }, NONE),
        ).toBe("1/12");
    });

    it("无结果集/pending → 空串", () => {
        expect(findCountText(FIND_STATE.pending, null, NONE)).toBe("");
        expect(findCountText(FIND_STATE.found, null, NONE)).toBe("");
        expect(findCountText(null, { current: 0, total: 0 }, NONE)).toBe("");
    });
});

describe("outlineColor", () => {
    it("三通道 → rgb()；缺省 → undefined", () => {
        expect(outlineColor(new Uint8ClampedArray([255, 0, 0]))).toBe(
            "rgb(255, 0, 0)",
        );
        expect(outlineColor([0, 0, 0])).toBe("rgb(0, 0, 0)");
        expect(outlineColor(null)).toBeUndefined();
        expect(outlineColor(undefined)).toBeUndefined();
        expect(outlineColor([1, 2])).toBeUndefined();
    });
});

describe("pageSizeText", () => {
    const orient = { portrait: "纵向", landscape: "横向" };

    it("缺数据 → 占位符", () => {
        expect(pageSizeText(null, orient)).toBe("—");
        expect(pageSizeText(undefined, orient)).toBe("—");
    });

    it("name + 尺寸 + 方向拼接", () => {
        expect(
            pageSizeText(
                {
                    width: "210",
                    height: "297",
                    unit: "mm",
                    name: "A4",
                    orientation: "portrait",
                },
                orient,
            ),
        ).toBe("A4 · 210 × 297 mm · 纵向");
    });

    it("无 name/未知方向时只出尺寸", () => {
        expect(
            pageSizeText({ width: "8.5", height: "11", unit: "in" }, orient),
        ).toBe("8.5 × 11 in");
    });
});

describe("fmtDate", () => {
    it("null/非法 → 占位符；合法 Date → 非空串", () => {
        expect(fmtDate(null)).toBe("—");
        expect(fmtDate(undefined)).toBe("—");
        expect(fmtDate(new Date("2026-09-16T12:00:00Z"))).not.toBe("—");
    });
});

describe("annotFileName（带批注副本文件名）", () => {
    it("{task}-{en|zh}-annotated.pdf", () => {
        expect(annotFileName("t_abc", "original")).toBe(
            "t_abc-en-annotated.pdf",
        );
        expect(annotFileName("t_abc", "translated")).toBe(
            "t_abc-zh-annotated.pdf",
        );
    });
});

describe("zoomToFontPx（html/dom 缩放 → 正文字号）", () => {
    it("非百分比的具名档位 → 默认 15px", () => {
        expect(zoomToFontPx("page-width")).toBe(15);
        expect(zoomToFontPx("page-fit")).toBe(15);
        expect(zoomToFontPx("auto")).toBe(15);
    });

    it("百分比 → 60%..200% 线性映射到 12..22px", () => {
        expect(zoomToFontPx("60%")).toBe(12);
        expect(zoomToFontPx("100%")).toBeCloseTo(14.9, 1);
        expect(zoomToFontPx("150%")).toBeCloseTo(18.4, 1);
        expect(zoomToFontPx("200%")).toBe(22);
    });

    it("出界百分比夹取到端点", () => {
        expect(zoomToFontPx("10%")).toBe(12);
        expect(zoomToFontPx("500%")).toBe(22);
    });
});
