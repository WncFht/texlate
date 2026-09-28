import { describe, expect, it } from "vitest";
import { resolveReaderView } from "../reader/view";

const chunk = { seq: 1, en: "a", zh: "甲" };

describe("resolveReaderView（html 视图降级门）", () => {
    it("info 未到 → loading", () => {
        expect(resolveReaderView(null, undefined)).toBe("loading");
        expect(resolveReaderView(undefined, { chunks: [chunk] })).toBe(
            "loading",
        );
    });

    it("view 缺省/为 pdf → pdf（不等 dual.json）", () => {
        expect(resolveReaderView({}, undefined)).toBe("pdf");
        expect(resolveReaderView({ view: "pdf" }, null)).toBe("pdf");
        expect(resolveReaderView({ view: "pdf" }, { chunks: [chunk] })).toBe(
            "pdf",
        );
    });

    it("view=html + dual.json 未落定 → loading（不闪 pdf 面板）", () => {
        expect(resolveReaderView({ view: "html" }, undefined)).toBe("loading");
    });

    it("view=html + chunks 非空 → html", () => {
        expect(resolveReaderView({ view: "html" }, { chunks: [chunk] })).toBe(
            "html",
        );
    });

    it("view=html + dual.json 拉取失败（null）→ empty", () => {
        expect(resolveReaderView({ view: "html" }, null)).toBe("empty");
    });

    it("view=html + chunks 空数组/缺字段 → empty（不出空 HtmlPane）", () => {
        expect(resolveReaderView({ view: "html" }, { chunks: [] })).toBe(
            "empty",
        );
        expect(resolveReaderView({ view: "html" }, {})).toBe("empty");
    });
});

describe("resolveReaderView（dom 视图——arxiv_html 链 DOM 产物）", () => {
    const doc = (url: string) => ({ version: "v", pages: 3, url });

    it("view=dom + 任一侧 documents.url 在 → dom（不等 dual.json）", () => {
        expect(
            resolveReaderView(
                { view: "dom", documents: { original: doc("/f/en.html") } },
                undefined,
            ),
        ).toBe("dom");
        expect(
            resolveReaderView(
                { view: "dom", documents: { translated: doc("/f/zh.html") } },
                undefined,
            ),
        ).toBe("dom");
    });

    it("view=dom + 双侧 url 全缺 → empty（坏数据同 html 无 chunks 档）", () => {
        expect(
            resolveReaderView({ view: "dom", documents: {} }, undefined),
        ).toBe("empty");
        expect(
            resolveReaderView(
                { view: "dom", documents: { original: doc("") } },
                { chunks: [chunk] },
            ),
        ).toBe("empty");
    });

    it("view=dom 不看 dual.chunks——有 chunks 也走 dom 臂", () => {
        expect(
            resolveReaderView(
                { view: "dom", documents: { original: doc("/f/en.html") } },
                { chunks: [chunk] },
            ),
        ).toBe("dom");
    });
});

describe("done-doc 决议（docx/epub 任务 reader 404 → files 产物面板）", () => {
    it("info 缺失 + readerGone → files", () => {
        expect(resolveReaderView(null, undefined, true)).toBe("files");
        expect(resolveReaderView(undefined, undefined, true)).toBe("files");
    });

    it("readerGone 缺省/false 时维持 loading（不动旧语义）", () => {
        expect(resolveReaderView(null, undefined)).toBe("loading");
        expect(resolveReaderView(null, undefined, false)).toBe("loading");
    });

    it("info 在则 readerGone 不改既有判定", () => {
        expect(resolveReaderView({ view: "pdf" }, null, true)).toBe("pdf");
        expect(
            resolveReaderView({ view: "html" }, { chunks: [chunk] }, true),
        ).toBe("html");
    });
});
