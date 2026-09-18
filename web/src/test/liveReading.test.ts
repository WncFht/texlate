// @vitest-environment jsdom
// live reading 面：
//  - mergeLive        轮询页合并（新增/变更/幂等/非法 seq）
//  - chunkUntranslated 徽标判定（status!=ok / 缺席 + zh 空兜底）
//  - parseHash        #/arxiv/{id} 深链分支
//  - LivePane         轮询累积渲染（未译段徽标+原文，zh 落地更新，卸载停轮询）
//  - HtmlPane         译文侧徽标 / 单段重译流（202→轮询→就地重绘+toast）
//  - Home             arxivId prop → 预填 + 自动提交一次
// marked/auto-render 桩掉——管线行为在 htmlPane.test.ts 已覆盖，这里测逻辑。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("marked", () => ({
    marked: { parse: (s: string) => `<p>${s}</p>` },
}));
vi.mock("katex/contrib/auto-render", () => ({ default: () => {} }));

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
    providers: vi.fn(),
    translate: vi.fn(),
    taskChunks: vi.fn(),
    retranslateChunk: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            tasks: mocks.tasks,
            health: mocks.health,
            getSettings: mocks.getSettings,
            providers: mocks.providers,
            translate: mocks.translate,
            taskChunks: mocks.taskChunks,
            retranslateChunk: mocks.retranslateChunk,
        },
    };
});

import { render } from "solid-js/web";
import { createSignal } from "solid-js";
import LivePane, { mergeLive, type LiveChunk } from "../reader/LivePane";
import HtmlPane from "../reader/HtmlPane";
import { chunkUntranslated } from "../reader/markdown";
import { parseHash } from "../App";
import Home from "../pages/Home";

const flush = () => new Promise((r) => setTimeout(r, 0));

let dispose: (() => void) | undefined;

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

beforeEach(() => {
    mocks.tasks.mockReset().mockResolvedValue({ tasks: [] });
    mocks.health
        .mockReset()
        .mockResolvedValue({ ok: true, version: "t", compilers: {} });
    mocks.getSettings.mockReset().mockResolvedValue({ has_api_key: false });
    mocks.providers.mockReset().mockResolvedValue({ providers: [] });
    mocks.translate.mockReset().mockResolvedValue({
        task_id: "t_0000000000000f01",
        status: "queued",
        events_url: "/api/task/t_0000000000000f01",
        reader_url: "/api/task/t_0000000000000f01/reader",
    });
    mocks.taskChunks.mockReset().mockResolvedValue({ chunks: [], total: 0 });
    mocks.retranslateChunk
        .mockReset()
        .mockResolvedValue({ task_id: "t1", seq: 0, status: "queued" });
});

// ---------- mergeLive：轮询页合并 ----------

describe("mergeLive —— taskChunks 页增量合并", () => {
    it("新增返回 dirty；同值行幂等跳过；字段变动返回 dirty", () => {
        const acc = new Map<number, LiveChunk>();
        let dirty = mergeLive(acc, [
            { seq: 0, status: "pending", en: "e0", zh: "" },
            { seq: 1, status: "ok", en: "e1", zh: "z1" },
        ]);
        expect(dirty.map((d) => d.seq)).toEqual([0, 1]);
        expect(acc.size).toBe(2);

        dirty = mergeLive(acc, [
            { seq: 0, status: "pending", en: "e0", zh: "" },
            { seq: 1, status: "ok", en: "e1", zh: "z1" },
        ]);
        expect(dirty).toEqual([]); // 整页重放零变化

        dirty = mergeLive(acc, [
            { seq: 0, status: "ok", en: "e0", zh: "z0" }, // status+zh 双变
            { seq: 1, status: "ok", en: "e1", zh: "z1" },
        ]);
        expect(dirty.map((d) => d.seq)).toEqual([0]);
        expect(acc.get(0)?.zh).toBe("z0");
    });

    it("非法 seq 丢弃；稀疏 seq 洞后补也收", () => {
        const acc = new Map<number, LiveChunk>();
        const dirty = mergeLive(acc, [
            { seq: Number.NaN, status: "ok", zh: "x" },
            { seq: 0, status: "ok", en: "e", zh: "z" },
            { seq: 4, status: "pending", en: "e4", zh: "" },
        ]);
        expect(dirty.map((d) => d.seq)).toEqual([0, 4]);
        expect(acc.has(Number.NaN)).toBe(false);
    });
});

// ---------- chunkUntranslated：徽标判定 ----------

describe("chunkUntranslated —— 未翻译判定", () => {
    it("status 在场以 !=ok 为准；ok+空 zh 也标（实际显原文）", () => {
        expect(chunkUntranslated({ status: "ok", zh: "译" })).toBe(false);
        expect(chunkUntranslated({ status: "fallback_orig", zh: "src" })).toBe(
            true,
        );
        expect(chunkUntranslated({ status: "failed", zh: "" })).toBe(true);
        expect(chunkUntranslated({ status: "pending", zh: "" })).toBe(true);
        expect(chunkUntranslated({ status: "ok", zh: "" })).toBe(true);
    });

    it("status 缺席（旧 dual.json）按 zh 是否为空兜底", () => {
        expect(chunkUntranslated({ zh: "译文" })).toBe(false);
        expect(chunkUntranslated({ zh: "" })).toBe(true);
        expect(chunkUntranslated({ zh: "   " })).toBe(true);
        expect(chunkUntranslated({})).toBe(true);
    });
});

// ---------- parseHash：#/arxiv/{id} 深链 ----------

describe("parseHash —— #/arxiv/{id} 深链", () => {
    it("新/旧式 arxiv id 进 home+arxivId；其余路由不变", () => {
        expect(parseHash("#/arxiv/2501.14787")).toEqual({
            page: "home",
            arxivId: "2501.14787",
        });
        expect(parseHash("#/arxiv/2501.14787v3")).toEqual({
            page: "home",
            arxivId: "2501.14787v3",
        });
        expect(parseHash("#/arxiv/cs/0501001")).toEqual({
            page: "home",
            arxivId: "cs/0501001",
        });
        expect(parseHash("#/reader/t_abc123")).toEqual({
            page: "reader",
            taskId: "t_abc123",
        });
        expect(parseHash("#/settings")).toEqual({ page: "settings" });
        expect(parseHash("#/")).toEqual({ page: "home" });
        expect(parseHash("")).toEqual({ page: "home" });
        // 空 id / 仅前缀不判深链——落裸 home（arxivId 缺席不触发自动提交）
        expect(parseHash("#/arxiv/")).toEqual({ page: "home" });
    });
});

// ---------- LivePane：轮询累积渲染 ----------

describe("LivePane —— 边译边读", () => {
    it("已译段渲 zh；未译段带徽标显原文；zh 落地后原位更新", async () => {
        mocks.taskChunks.mockResolvedValue({
            total: 5,
            chunks: [
                { seq: 0, kind: "text", status: "ok", en: "e0", zh: "译文0" },
                { seq: 1, kind: "text", status: "pending", en: "e1", zh: "" },
            ],
        });
        dispose = render(() => LivePane({ taskId: "t_live" }), document.body);
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                2,
            ),
        );

        const secs = document.body.querySelectorAll("[data-chunk]");
        expect(secs[0].textContent).toContain("译文0");
        expect(secs[0].querySelector(".chunk-badge")).toBeNull();
        expect(secs[1].querySelector(".chunk-badge")).not.toBeNull();
        expect(secs[1].textContent).toContain("e1");

        // 第二拍 seq1 翻好——同节原位更新、徽标摘除（轮询 2.5s 一拍，放宽等待窗）
        mocks.taskChunks.mockResolvedValue({
            total: 5,
            chunks: [
                { seq: 0, kind: "text", status: "ok", en: "e0", zh: "译文0" },
                { seq: 1, kind: "text", status: "ok", en: "e1", zh: "译文1" },
            ],
        });
        await vi.waitFor(
            () =>
                expect(
                    document.body.querySelector('[data-chunk="1"]')
                        ?.textContent,
                ).toContain("译文1"),
            { timeout: 4000 },
        );
        expect(
            document.body
                .querySelector('[data-chunk="1"]')
                ?.querySelector(".chunk-badge"),
        ).toBeNull();
    });

    it("卸载即停轮询", async () => {
        dispose = render(() => LivePane({ taskId: "t_stop" }), document.body);
        await vi.waitFor(() => expect(mocks.taskChunks).toHaveBeenCalled());
        dispose();
        dispose = undefined;
        const n = mocks.taskChunks.mock.calls.length;
        await new Promise((r) => setTimeout(r, 2600));
        expect(mocks.taskChunks.mock.calls.length).toBe(n);
    });
});

// ---------- HtmlPane：徽标 + 单段重译 ----------

describe("HtmlPane —— 未翻译徽标", () => {
    const mount = (
        side: "original" | "translated",
        chunks: never[] | object[],
    ) =>
        render(
            () =>
                HtmlPane({
                    side,
                    chunks: chunks as never,
                }),
            document.body,
        );

    it("译文侧：status!=ok 与旧文件空 zh 带徽标；ok 段不标；原文侧恒不标", async () => {
        dispose = mount("translated", [
            { seq: 0, en: "e0", zh: "译文0", status: "ok" },
            { seq: 1, en: "e1", zh: "e1", status: "fallback_orig" },
            { seq: 2, en: "e2", zh: "" }, // status 缺席 + zh 空 → 标
            { seq: 3, en: "e3", zh: "译文3" }, // status 缺席 + zh 有 → 不标
        ]);
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                4,
            ),
        );
        const badge = (i: number) =>
            document.body
                .querySelector(`[data-chunk="${i}"]`)
                ?.querySelector(".chunk-badge");
        expect(badge(0)).toBeNull();
        expect(badge(1)).not.toBeNull();
        expect(badge(2)).not.toBeNull();
        expect(badge(3)).toBeNull();
    });

    it("原文侧任何状态都不挂徽标", async () => {
        dispose = mount("original", [
            { seq: 0, en: "e0", zh: "", status: "failed" },
        ]);
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                1,
            ),
        );
        expect(document.body.querySelector(".chunk-badge")).toBeNull();
    });
});

describe("HtmlPane —— 单段重译", () => {
    it("202 → 轮询 zh 落地 → 就地重绘 + toast；徽标随新状态摘除", async () => {
        mocks.taskChunks.mockResolvedValue({
            total: 2,
            chunks: [
                { seq: 1, kind: "text", status: "ok", en: "e1", zh: "新译文1" },
            ],
        });
        dispose = render(
            () =>
                HtmlPane({
                    side: "translated",
                    taskId: "t_retx",
                    canRetranslate: true,
                    chunks: [
                        { seq: 0, en: "e0", zh: "译文0", status: "ok" },
                        { seq: 1, en: "e1", zh: "", status: "failed" },
                    ],
                }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                2,
            ),
        );

        const btn =
            document.body.querySelector<HTMLButtonElement>('[data-retx="1"]');
        expect(btn).not.toBeNull();
        btn!.click();
        expect(mocks.retranslateChunk).toHaveBeenCalledWith("t_retx", 1);
        await vi.waitFor(
            () =>
                expect(
                    document.body.querySelector('[data-chunk="1"]')
                        ?.textContent,
                ).toContain("新译文1"),
            { timeout: 5000 },
        );
        expect(
            document.body
                .querySelector('[data-chunk="1"]')
                ?.querySelector(".chunk-badge"),
        ).toBeNull();
        expect(
            document.body.querySelector(".pane-toast")?.textContent,
        ).toContain("译文已更新");
    });

    it("提交被拒 → 按钮复位 + 错误 toast", async () => {
        const { ApiError } = await import("../api/client");
        mocks.retranslateChunk.mockRejectedValue(
            new ApiError(409, "task not terminal"),
        );
        dispose = render(
            () =>
                HtmlPane({
                    side: "translated",
                    taskId: "t_retx",
                    canRetranslate: true,
                    chunks: [{ seq: 0, en: "e0", zh: "", status: "failed" }],
                }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                1,
            ),
        );
        const btn =
            document.body.querySelector<HTMLButtonElement>('[data-retx="0"]')!;
        btn.click();
        await vi.waitFor(() => expect(btn.disabled).toBe(false));
        expect(
            document.body.querySelector(".pane-toast")?.textContent,
        ).toContain("重译提交失败");
    });

    it("canRetranslate/taskId 缺席 → 不挂钮（进行中隐藏）", async () => {
        dispose = render(
            () =>
                HtmlPane({
                    side: "translated",
                    chunks: [{ seq: 0, en: "e0", zh: "z0" }],
                }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                1,
            ),
        );
        expect(document.body.querySelector(".chunk-retx")).toBeNull();
    });
});

// ---------- Home：arxivId prop 深链自动提交 ----------

describe("Home —— #/arxiv/{id} 深链", () => {
    it("arxivId prop → 预填输入框 + 自动提交一次", async () => {
        const nav = vi.fn();
        dispose = render(
            () => Home({ nav, arxivId: "2501.14787" }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(mocks.translate).toHaveBeenCalledTimes(1),
        );
        expect(mocks.translate).toHaveBeenCalledWith(
            "2501.14787",
            undefined,
            undefined,
        );
        expect(
            document.body.querySelector<HTMLInputElement>(".arxiv-input")
                ?.value,
        ).toBe("2501.14787");
        await flush();
        expect(mocks.translate).toHaveBeenCalledTimes(1); // 不重入
    });

    it("无 arxivId 不自动提交；prop 变化到新 id 才再提", async () => {
        const nav = vi.fn();
        const [aid, setAid] = createSignal<string | undefined>(undefined);
        // JSX props 编译成 getter——直调组件要保持反应性须手写 getter
        const props = {
            nav,
            get arxivId() {
                return aid();
            },
        };
        dispose = render(() => Home(props), document.body);
        await flush();
        expect(mocks.translate).not.toHaveBeenCalled();

        setAid("2501.14787");
        await vi.waitFor(() =>
            expect(mocks.translate).toHaveBeenCalledTimes(1),
        );
        // 同值再置不触发（effect 守卫 + signal 同值不重新跑）
        setAid("2501.14787");
        await flush();
        expect(mocks.translate).toHaveBeenCalledTimes(1);

        setAid("cs/0501001");
        await vi.waitFor(() =>
            expect(mocks.translate).toHaveBeenCalledTimes(2),
        );
        expect(mocks.translate).toHaveBeenLastCalledWith(
            "cs/0501001",
            undefined,
            undefined,
        );
    });
});
