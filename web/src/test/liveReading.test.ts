// @vitest-environment jsdom
// live reading 面：
//  - mergeLive        轮询页合并（新增/变更/幂等/非法 seq）
//  - chunkUntranslated 徽标判定（status!=ok / 缺席 + zh 空兜底）
//  - parseHash        #/arxiv/{id} 深链分支
//  - LivePane         轮询累积渲染（未译段徽标+原文，zh 落地更新，卸载停轮询）
//  - HtmlPane         译文侧徽标 / 单段重译流（202→轮询→就地重绘+toast）
//  - Home             arxivId prop → 预填 + 聚焦翻译钮，不自动提交
// marked/auto-render 桩掉——管线行为在 htmlPane.test.ts 已覆盖，这里测逻辑。

import { beforeEach, describe, expect, it, vi } from "vitest";

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

// vi.mock 工厂收敛到 _taskkit.clientModuleMock——mocks 全键进 api 覆写
//（本文件无 openTaskEvents 等顶层导出要换；顶层键分流口径见 _taskkit 头注）
vi.mock("../api/client", async (importOriginal) => {
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

import { createSignal } from "solid-js";
import LivePane, { mergeLive, type LiveChunk } from "../reader/panes/LivePane";
import HtmlPane from "../reader/panes/HtmlPane";
import { chunkUntranslated } from "../reader/logic/markdown";
import { parseHash } from "../App";
import Home from "../pages/Home";
import { taskStore } from "../stores/tasks";
import { t } from "../i18n";
import type { DualChunk } from "../api/client";
import { flush } from "./_taskkit";
import { FM_OPTS, resetHomeMocks } from "./_homekit";
import { mountToBody, unmountLast } from "./helpers";

beforeEach(() => {
    // Home 面成员（tasks/health/getSettings/providers/translate→RESP）走
    // _homekit 统一复位；taskChunks/retranslateChunk 是 reader 面键，本地补值
    resetHomeMocks(mocks);
    mocks.taskChunks.mockResolvedValue({ chunks: [], total: 0 });
    mocks.retranslateChunk.mockResolvedValue({
        task_id: "t1",
        seq: 0,
        status: "queued",
    });
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
        expect(parseHash("#/tasks")).toEqual({ page: "tasks" });
        expect(parseHash("#/discover")).toEqual({ page: "discover" });
        expect(parseHash("#/settings")).toEqual({ page: "settings" });
        expect(parseHash("#/")).toEqual({ page: "home" });
        expect(parseHash("")).toEqual({ page: "home" });
        // 空 id / 仅前缀不判深链——落裸 home（arxivId 缺席不触发自动提交）
        expect(parseHash("#/arxiv/")).toEqual({ page: "home" });
        // % 不在 id 字符集（[A-Za-z0-9._/-]）——畸形转义到不了
        // decodeURIComponent，整条落裸 home（App.tsx 的 catch 因此是死分支）
        expect(parseHash("#/arxiv/%E0%A4")).toEqual({ page: "home" });
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
        mountToBody(() => LivePane({ taskId: "t_live" }));
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

    it("折叠期间只记不绘，展开按最新快照补渲", async () => {
        mocks.taskChunks.mockResolvedValue({
            total: 3,
            chunks: [
                { seq: 0, kind: "text", status: "ok", en: "e0", zh: "译文0" },
            ],
        });
        mountToBody(() => LivePane({ taskId: "t_fold" }));
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                1,
            ),
        );

        // 合上 → 后续拍新段不上屏
        const det =
            document.body.querySelector<HTMLDetailsElement>(
                "details.live-pane",
            )!;
        det.open = false;
        det.dispatchEvent(new Event("toggle"));
        mocks.taskChunks.mockResolvedValue({
            total: 3,
            chunks: [
                { seq: 0, kind: "text", status: "ok", en: "e0", zh: "译文0" },
                { seq: 1, kind: "text", status: "ok", en: "e1", zh: "译文1" },
            ],
        });
        // 轮询 2.5s 一拍——等下一拍真落地再断言（调用数 > 首拍）
        const calls0 = mocks.taskChunks.mock.calls.length;
        await vi.waitFor(
            () =>
                expect(mocks.taskChunks.mock.calls.length).toBeGreaterThan(
                    calls0,
                ),
            { timeout: 4000 },
        );
        await flush();
        expect(document.body.querySelector('[data-chunk="1"]')).toBeNull();

        // 展开 → 补渲到位（acc 最新快照，含折叠期积下的段）
        det.open = true;
        det.dispatchEvent(new Event("toggle"));
        await vi.waitFor(() =>
            expect(
                document.body.querySelector('[data-chunk="1"]')?.textContent,
            ).toContain("译文1"),
        );
    });

    it("卸载即停轮询", async () => {
        // chunkPoll 走 window.setInterval(POLL_MS=2500)——假时钟免真等 2.6s
        vi.useFakeTimers();
        try {
            mountToBody(() => LivePane({ taskId: "t_stop" }));
            await vi.waitFor(() => expect(mocks.taskChunks).toHaveBeenCalled());
            unmountLast();
            const n = mocks.taskChunks.mock.calls.length;
            await vi.advanceTimersByTimeAsync(2600);
            expect(mocks.taskChunks.mock.calls.length).toBe(n);
        } finally {
            vi.useRealTimers();
        }
    });
});

// ---------- HtmlPane：徽标 + 单段重译 ----------

describe("HtmlPane —— 未翻译徽标", () => {
    const mount = (side: "original" | "translated", chunks: DualChunk[]) =>
        mountToBody(() =>
            HtmlPane({
                side,
                chunks,
            }),
        );

    it("译文侧：status!=ok 与旧文件空 zh 带徽标；ok 段不标；原文侧恒不标", async () => {
        mount("translated", [
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
        mount("original", [{ seq: 0, en: "e0", zh: "", status: "failed" }]);
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
        mountToBody(() =>
            HtmlPane({
                side: "translated",
                taskId: "t_retx",
                canRetranslate: true,
                chunks: [
                    { seq: 0, en: "e0", zh: "译文0", status: "ok" },
                    { seq: 1, en: "e1", zh: "", status: "failed" },
                ],
            }),
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
        ).toContain(t.live.retxDone);
    });

    it("提交被拒 → 按钮复位 + 错误 toast", async () => {
        const { ApiError } = await import("../api/client");
        mocks.retranslateChunk.mockRejectedValue(
            new ApiError(409, "task not terminal"),
        );
        mountToBody(() =>
            HtmlPane({
                side: "translated",
                taskId: "t_retx",
                canRetranslate: true,
                chunks: [{ seq: 0, en: "e0", zh: "", status: "failed" }],
            }),
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
        ).toContain(t.live.retxFail);
    });

    it("canRetranslate/taskId 缺席 → 不挂钮（进行中隐藏）", async () => {
        mountToBody(() =>
            HtmlPane({
                side: "translated",
                chunks: [{ seq: 0, en: "e0", zh: "z0" }],
            }),
        );
        await vi.waitFor(() =>
            expect(document.body.querySelectorAll("[data-chunk]").length).toBe(
                1,
            ),
        );
        expect(document.body.querySelector(".chunk-retx")).toBeNull();
    });
});

// ---------- Home：arxivId prop 深链预填（不自动提交） ----------

describe("Home —— #/arxiv/{id} 深链", () => {
    it("arxivId prop → 预填输入框 + 聚焦翻译钮，用户拍板才提交", async () => {
        const nav = vi.fn();
        mountToBody(() => Home({ nav, arxivId: "2501.14787" }));
        await flush();
        // 挂载触发 ensureFresh→refresh：api.tasks 裸数组契约下成功路径
        // 不挂 loadError（信封形 mock 会让 refresh 抛错留下 loadError）
        expect(taskStore.state.loadError).toBeUndefined();
        // 不自动烧任务——输入框预填、焦点落翻译钮待命
        expect(mocks.translate).not.toHaveBeenCalled();
        expect(
            document.body.querySelector<HTMLInputElement>(".arxiv-input")
                ?.value,
        ).toBe("2501.14787");
        const submit =
            document.body.querySelector<HTMLButtonElement>(".btn-primary")!;
        expect(document.activeElement).toBe(submit);

        // 用户确认（Enter 隐式提交同路）才发出 translate
        document.body
            .querySelector("form")!
            .dispatchEvent(
                new Event("submit", { bubbles: true, cancelable: true }),
            );
        await vi.waitFor(() =>
            expect(mocks.translate).toHaveBeenCalledTimes(1),
        );
        expect(mocks.translate).toHaveBeenCalledWith(
            "2501.14787",
            FM_OPTS,
            undefined,
        );
    });

    it("无 arxivId 不预填不提交；prop 变化到新 id 再预填", async () => {
        const nav = vi.fn();
        const [aid, setAid] = createSignal<string | undefined>(undefined);
        // JSX props 编译成 getter——直调组件要保持反应性须手写 getter
        const props = {
            nav,
            get arxivId() {
                return aid();
            },
        };
        mountToBody(() => Home(props));
        await flush();
        expect(mocks.translate).not.toHaveBeenCalled();
        const input = () =>
            document.body.querySelector<HTMLInputElement>(".arxiv-input")!;

        setAid("2501.14787");
        await flush();
        expect(input().value).toBe("2501.14787");
        expect(mocks.translate).not.toHaveBeenCalled();

        // 同值再置不重聚焦（effect 守卫）
        setAid("2501.14787");
        await flush();
        expect(input().value).toBe("2501.14787");

        setAid("cs/0501001");
        await flush();
        expect(input().value).toBe("cs/0501001");
        expect(mocks.translate).not.toHaveBeenCalled();
    });
});
