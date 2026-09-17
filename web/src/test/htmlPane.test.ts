// @vitest-environment jsdom
// HtmlPane 坏数据面：marked.parse 单 chunk 抛错 → 该块降级为转义原文，
// 整页不炸；相邻 chunk 正常渲染。marked 模块级桩掉（真实 marked 几乎不抛，
// 这里注入确定性失败）。

import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("marked", () => ({
    marked: {
        parse: (s: string) => {
            if (s.includes("BAD-CHUNK")) throw new Error("marked exploded");
            return `<p>${s}</p>`;
        },
    },
}));

import { render } from "solid-js/web";
import HtmlPane from "../reader/HtmlPane";

const flush = () => new Promise((r) => setTimeout(r, 0));
let dispose: (() => void) | undefined;

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("HtmlPane chunk 解析失败兜底", () => {
    it("单 chunk marked 抛错 → 转义原文落盘，不炸整页", async () => {
        const onReady = vi.fn();
        dispose = render(
            () =>
                HtmlPane({
                    side: "original",
                    chunks: [
                        { seq: 0, en: "good chunk" },
                        { seq: 1, en: "BAD-CHUNK <b>raw</b>" },
                        { seq: 2, en: "tail chunk" },
                    ],
                    onReady,
                }),
            document.body,
        );
        await flush();
        await flush();

        const body = document.body.querySelector(".pane-html-body");
        expect(body).not.toBeNull();
        const chunks = body!.querySelectorAll("[data-chunk]");
        expect(chunks.length).toBe(3);
        // 坏块：源文按纯文本转义呈现——<b> 不成元素
        expect(chunks[1].innerHTML).toContain("&lt;b&gt;raw&lt;/b&gt;");
        expect(chunks[1].querySelector("b")).toBeNull();
        // 好块正常渲染；onReady 照报（页面级不炸）
        expect(chunks[0].textContent).toContain("good chunk");
        expect(onReady).toHaveBeenCalled();
    });

    it("seq 非整型不逃逸 data-chunk 属性（share.zip 导入的 dual.json 是外部输入）", async () => {
        dispose = render(
            () =>
                HtmlPane({
                    side: "original",
                    chunks: [
                        { seq: 0, en: "ok" },
                        // 外部 JSON 可塞任意类型——突破属性引号即注入
                        { seq: '1"><img onerror="x()">' as never, en: "bad" },
                    ],
                }),
            document.body,
        );
        await flush();
        await flush();

        const chunks = document.body.querySelectorAll("[data-chunk]");
        expect(chunks.length).toBe(2);
        expect(chunks[1].getAttribute("data-chunk")).toBe('1"><img onerror="x()">');
        expect(chunks[1].querySelector("img")).toBeNull();
    });
});
