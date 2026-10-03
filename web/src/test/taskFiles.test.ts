import { describe, expect, it } from "vitest";
import { landingHash } from "../api/client";
import { t } from "../i18n";
import { downloadItems, fmtBytes, isDocKind } from "../taskFiles";

describe("fmtBytes", () => {
    it("非法/缺失 → 占位符", () => {
        expect(fmtBytes(undefined)).toBe("—");
        expect(fmtBytes(null)).toBe("—");
        expect(fmtBytes(-5)).toBe("—");
        expect(fmtBytes(Number.NaN)).toBe("—");
    });

    it("分档：B / KB / MB", () => {
        expect(fmtBytes(0)).toBe("0 B");
        expect(fmtBytes(512)).toBe("512 B");
        expect(fmtBytes(2048)).toBe("2.0 KB");
        expect(fmtBytes(5 * 1024 * 1024)).toBe("5.0 MB");
        expect(fmtBytes(150 * 1024)).toBe("150 KB");
    });
});

describe("isDocKind（无对照阅读器的插译产物路）", () => {
    it("docx/epub → true", () => {
        expect(isDocKind("docx")).toBe(true);
        expect(isDocKind("epub")).toBe(true);
    });

    it("tex/pdf 路与未知 kind → false（upload_pdf 产 dual.json 有阅读器）", () => {
        for (const k of [
            "arxiv",
            "upload_tex",
            "upload_pdf",
            "share",
            "mystery",
        ]) {
            expect(isDocKind(k)).toBe(false);
        }
    });
});

describe("downloadItems（db kind → 有序直链）", () => {
    it("db kind 映射 url kind + t.files 标签 + ?download=1", () => {
        const items = downloadItems({
            zh_docx: "/api/files/t_x/zh.docx",
            src_tar: "/api/files/t_x/src.tar",
        });
        // label 从 t.files 表取值——不断言字面文案：宿主 navigator.language
        // 决定 zh/en（CI=en-US 与 zh 开发机产出不同字面），本用例钉的是
        // kind→url kind 映射 + 标签来源 + ?download=1
        expect(items).toEqual([
            {
                kind: "zh.docx",
                label: t.files["zh.docx"],
                url: "/api/files/t_x/zh.docx?download=1",
            },
            {
                kind: "src.tar",
                label: t.files["src.tar"],
                url: "/api/files/t_x/src.tar?download=1",
            },
        ]);
    });

    it("排序：译文产物在前，源码/日志殿后", () => {
        const items = downloadItems({
            compile_log: "/f/compile.log",
            zh_pdf: "/f/zh.pdf",
            src_tar: "/f/src.tar",
            en_pdf: "/f/en.pdf",
        });
        expect(items.map((i) => i.kind)).toEqual([
            "zh.pdf",
            "en.pdf",
            "compile.log",
            "src.tar",
        ]);
    });

    it("未知 db kind 原样透出并排尾", () => {
        const items = downloadItems({
            future_kind: "/f/future",
            zh_epub: "/f/zh.epub",
        });
        expect(items.map((i) => i.kind)).toEqual(["zh.epub", "future_kind"]);
        expect(items[1].label).toBe("future_kind");
    });

    it("空 artifacts → 空清单（不渲染下载入口）", () => {
        expect(downloadItems({})).toEqual([]);
    });
});

describe("landingHash（reader_url 缺席降级）", () => {
    it("reader_url 在 → 按其 task_id 落地阅读器路由", () => {
        expect(
            landingHash({
                task_id: "t_aaaaaaaaaaaaaaaa",
                reader_url: "/api/task/t_aaaaaaaaaaaaaaaa/reader",
            }),
        ).toBe("#/reader/t_aaaaaaaaaaaaaaaa");
    });

    it("reader_url 缺席（docx/epub 上传）→ 回 task_id 详情面", () => {
        expect(landingHash({ task_id: "t_bbbbbbbbbbbbbbbb" })).toBe(
            "#/reader/t_bbbbbbbbbbbbbbbb",
        );
    });

    it("reader_url 形状异常 → 回 task_id，不崩", () => {
        expect(
            landingHash({ task_id: "t_cccccccccccccccc", reader_url: "/oops" }),
        ).toBe("#/reader/t_cccccccccccccccc");
        expect(
            landingHash({ task_id: "t_cccccccccccccccc", reader_url: "" }),
        ).toBe("#/reader/t_cccccccccccccccc");
    });
});
