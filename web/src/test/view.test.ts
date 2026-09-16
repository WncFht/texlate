import { describe, expect, it } from "vitest";
import { resolveReaderView } from "../reader/view";

const chunk = { seq: 1, en: "a", zh: "甲" };

describe("resolveReaderView（html 视图降级门）", () => {
    it("info 未到 → loading", () => {
        expect(resolveReaderView(null, undefined)).toBe("loading");
        expect(resolveReaderView(undefined, { chunks: [chunk] })).toBe("loading");
    });

    it("view 缺省/为 pdf → pdf（不等 dual.json）", () => {
        expect(resolveReaderView({}, undefined)).toBe("pdf");
        expect(resolveReaderView({ view: "pdf" }, null)).toBe("pdf");
        expect(resolveReaderView({ view: "pdf" }, { chunks: [chunk] })).toBe("pdf");
    });

    it("view=html + dual.json 未落定 → loading（不闪 pdf 面板）", () => {
        expect(resolveReaderView({ view: "html" }, undefined)).toBe("loading");
    });

    it("view=html + chunks 非空 → html", () => {
        expect(resolveReaderView({ view: "html" }, { chunks: [chunk] })).toBe("html");
    });

    it("view=html + dual.json 拉取失败（null）→ empty", () => {
        expect(resolveReaderView({ view: "html" }, null)).toBe("empty");
    });

    it("view=html + chunks 空数组/缺字段 → empty（不出空 HtmlPane）", () => {
        expect(resolveReaderView({ view: "html" }, { chunks: [] })).toBe("empty");
        expect(resolveReaderView({ view: "html" }, {})).toBe("empty");
    });
});
