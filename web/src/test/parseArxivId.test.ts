// @vitest-environment jsdom
// parseArxivId —— arXiv 输入解析：裸 id（新/旧式）、各路径 URL、
// arXiv: 前缀、.pdf/vN/查询参数容错，以及非法输入拒绝。
// 口径对齐服务端 fetch.normalize_arxiv_id（比它窄一点是刻意的：
// 前端只兜底常见粘贴形态，怪输入留给服务端 400 回来报错）。

import { describe, expect, it } from "vitest";
import { parseArxivId } from "../pages/Home";

describe("parseArxivId —— 裸 id", () => {
    it("新式 id", () => {
        expect(parseArxivId("2501.14787")).toBe("2501.14787");
        expect(parseArxivId("2501.14787v2")).toBe("2501.14787v2");
        expect(parseArxivId("  2501.14787  ")).toBe("2501.14787");
    });

    it("旧式 archive/NNNNNNN id", () => {
        expect(parseArxivId("hep-th/9901001")).toBe("hep-th/9901001");
        expect(parseArxivId("cs/0501001")).toBe("cs/0501001");
        expect(parseArxivId("math.AG/0601001")).toBe("math.AG/0601001");
        expect(parseArxivId("hep-th/9901001v3")).toBe("hep-th/9901001v3");
    });

    it("arXiv: 前缀与裸 .pdf 后缀", () => {
        expect(parseArxivId("arXiv:2501.14787")).toBe("2501.14787");
        expect(parseArxivId("arxiv: hep-th/9901001")).toBe("hep-th/9901001");
        expect(parseArxivId("2501.14787.pdf")).toBe("2501.14787");
    });
});

describe("parseArxivId —— URL", () => {
    it("abs/pdf 链接（新式 + 旧式）", () => {
        expect(parseArxivId("https://arxiv.org/abs/2501.14787")).toBe(
            "2501.14787",
        );
        expect(parseArxivId("https://arxiv.org/abs/hep-th/9901001")).toBe(
            "hep-th/9901001",
        );
        expect(parseArxivId("https://arxiv.org/pdf/hep-th/9901001")).toBe(
            "hep-th/9901001",
        );
        expect(parseArxivId("https://arxiv.org/pdf/2501.14787.pdf")).toBe(
            "2501.14787",
        );
        expect(parseArxivId("https://arxiv.org/pdf/2501.14787v2.pdf")).toBe(
            "2501.14787v2",
        );
    });

    it("其它路径段（html/src/format/e-print）+ 查询/锚点", () => {
        expect(parseArxivId("https://arxiv.org/html/2501.14787v1")).toBe(
            "2501.14787v1",
        );
        expect(parseArxivId("https://arxiv.org/format/2501.14787")).toBe(
            "2501.14787",
        );
        expect(parseArxivId("arxiv.org/abs/2501.14787?utm_source=x#y")).toBe(
            "2501.14787",
        );
        expect(parseArxivId("https://arxiv.org/abs/2501.14787/")).toBe(
            "2501.14787",
        );
    });
});

describe("parseArxivId —— 拒绝", () => {
    it("非 arXiv 输入返回 null", () => {
        expect(parseArxivId("")).toBeNull();
        expect(parseArxivId("not-an-id")).toBeNull();
        expect(parseArxivId("https://example.com/2501.14787")).toBeNull();
        expect(parseArxivId("https://arxiv.org/abs/2501.147")).toBeNull();
        expect(
            parseArxivId("https://arxiv.org/abs/2501.14787/extra"),
        ).toBeNull();
        expect(parseArxivId("12345678")).toBeNull();
    });
});
