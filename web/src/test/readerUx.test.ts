// @vitest-environment jsdom
// U 系交互件回归：
//  - externalLinksBlank：正文内 http(s) 外链一律新窗 + noopener（U2）
//  - previewText：空白塌缩 + 500 字截断
//  - ChunkPreview：api.taskChunks 轮询 → 已译段预览列表（U1）

import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";

const mocks = vi.hoisted(() => ({ taskChunks: vi.fn() }));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            taskChunks: mocks.taskChunks,
        },
    };
});

import ChunkPreview, { previewText } from "../reader/ChunkPreview";
import { externalLinksBlank } from "../reader/paneUtils";

let dispose: (() => void) | undefined;

afterEach(() => {
    dispose?.();
    dispose = undefined;
    mocks.taskChunks.mockReset();
    document.body.innerHTML = "";
});

describe("externalLinksBlank", () => {
    it("http(s) 外链 → target=_blank + noopener；锚点/相对链不动", () => {
        const root = document.createElement("div");
        root.innerHTML =
            '<a href="https://arxiv.org/abs/1">a</a>' +
            '<a href="http://x.test">b</a>' +
            '<a href="#sec">c</a>' +
            '<a href="/rel">d</a>';
        externalLinksBlank(root);
        const [a, b, c, d] = [...root.querySelectorAll("a")].map((el) => ({
            target: el.target,
            rel: el.rel,
        }));
        expect(a).toEqual({ target: "_blank", rel: "noopener noreferrer" });
        expect(b.target).toBe("_blank");
        expect(c.target).toBe("");
        expect(d.target).toBe("");
    });
});

describe("previewText", () => {
    it("空白塌缩 + 500 字截断带省略号；非字符串 → 空", () => {
        expect(previewText("  第一 \n 段  翻译 ")).toBe("第一 段 翻译");
        expect(previewText(undefined)).toBe("");
        const long = "x".repeat(600);
        const out = previewText(long);
        expect(out).toHaveLength(501);
        expect(out.endsWith("…")).toBe(true);
    });
});

describe("ChunkPreview（api.taskChunks 数据流）", () => {
    it("只列有 zh 的段：序号/kind 徽标 + 头计数 + 窗口参数", async () => {
        mocks.taskChunks.mockResolvedValue({
            total: 4,
            chunks: [
                { seq: 0, kind: "para", status: "ok", zh: "第一段翻译" },
                { seq: 1, status: "pending" },
                { seq: 2, kind: "section", status: "ok", zh: "第三节" },
                { seq: 3, status: "ok", zh: "   " },
            ],
        });
        dispose = render(() => ChunkPreview({ taskId: "t1" }), document.body);
        await vi.waitFor(() =>
            expect(document.querySelectorAll(".cp-item")).toHaveLength(2),
        );
        expect(document.querySelector(".cp-head")?.textContent).toContain("2/4");
        const metas = [...document.querySelectorAll(".cp-meta")].map(
            (el) => el.textContent,
        );
        expect(metas[0]).toContain("#1");
        expect(metas[1]).toContain("#3");
        expect(document.querySelectorAll(".cp-kind")).toHaveLength(2);
        // 共享轮询（chunkPoll）按 CHUNK_WINDOW 整窗拉——预览显示侧仍切头 60 段
        expect(mocks.taskChunks).toHaveBeenCalledWith("t1", 0, 500);
    });

    it("端点报错 → 静默缺席不炸（下拍再试）", async () => {
        mocks.taskChunks.mockRejectedValue(new Error("404"));
        dispose = render(() => ChunkPreview({ taskId: "t2" }), document.body);
        await new Promise((r) => setTimeout(r, 10));
        expect(document.querySelector(".chunk-preview")).toBeNull();
    });
});
