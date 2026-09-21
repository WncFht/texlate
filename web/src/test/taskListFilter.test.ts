// @vitest-environment jsdom
// TaskList U5/U8：搜索 + 筛选 chips + 活动置顶分组 + 批量瘦身/删除已结束；
// 行内 ⏻ 取消（在途）/ ↻ 重试（可重试终态）/ ⚙ 设置链（needs_auth）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    cancel: vi.fn(),
    retry: vi.fn(),
    files: vi.fn(),
    slimTasks: vi.fn(),
    remove: vi.fn(),
    resetLive: vi.fn(),
    refresh: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            cancel: mocks.cancel,
            retry: mocks.retry,
            files: mocks.files,
            slimTasks: mocks.slimTasks,
        },
    };
});

vi.mock("../stores/tasks", () => ({
    taskStore: {
        remove: mocks.remove,
        resetLive: mocks.resetLive,
        refresh: mocks.refresh,
    },
}));

import type { TaskSnapshot } from "../api/client";
import { t } from "../i18n";
import { flush, snap } from "./_taskkit";
import { renderList as mountList } from "./_taskdom";

let dispose: (() => void) | undefined;
let root: HTMLDivElement;

const rows = () => [...root.querySelectorAll(".task-row")];
const titles = () =>
    [...root.querySelectorAll(".task-title")].map((x) => x.textContent);
const click = (el: Element) =>
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));

const seed: TaskSnapshot[] = [
    snap("a2", { title: "done beta", created_at: 1_700_000_100 }),
    snap("a1", { title: "active alpha", status: "translating", progress: 40 }),
    snap("a3", { title: "fault gamma", status: "fault" }),
    snap("a4", { title: "auth delta", status: "needs_auth" }),
    snap("a5", { title: "done epsilon", created_at: 1_700_000_200 }),
];

beforeEach(() => {
    root = document.createElement("div");
    document.body.appendChild(root);
    mocks.cancel.mockReset().mockResolvedValue({ task_id: "x" });
    mocks.retry.mockReset().mockResolvedValue({ task_id: "x" });
    mocks.files.mockReset().mockResolvedValue({ artifacts: {} });
    mocks.slimTasks
        .mockReset()
        .mockResolvedValue({ slimmed: 2, freed_bytes: 1_500_000 });
    mocks.remove.mockReset().mockResolvedValue(undefined);
    mocks.resetLive.mockReset();
    mocks.refresh.mockReset();
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    root.remove();
    vi.restoreAllMocks();
});

const renderList = (tasks = seed) => {
    dispose = mountList(tasks, root);
};

describe("U5：搜索 + 筛选 + 活动置顶", () => {
    it("默认全量：活动任务排最前，终态按时间新→旧", () => {
        renderList();
        expect(titles()[0]).toBe("active alpha");
        expect(rows()).toHaveLength(5);
    });

    it("搜索子串过滤（标题/ID 命中）", async () => {
        renderList();
        const inp = root.querySelector(".task-search") as HTMLInputElement;
        inp.value = "epsilon";
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        await flush();
        expect(titles()).toEqual(["done epsilon"]);

        // task_id 命中同一 hay 串（title 不含该子串——走的是 ID 臂）
        inp.value = "a5";
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        await flush();
        expect(titles()).toEqual(["done epsilon"]);
    });

    it("筛选 chips：进行中/已完成/异常", async () => {
        renderList();
        const chip = (label: string) =>
            [...root.querySelectorAll(".task-chip")].find(
                (b) => b.textContent?.startsWith(label),
            )!;
        click(chip(t.home.fActive));
        await flush();
        expect(titles()).toEqual(["active alpha"]);
        click(chip(t.home.fDone));
        await flush();
        expect(titles()).toEqual(["done epsilon", "done beta"]);
        click(chip(t.home.fFailed));
        await flush();
        expect(titles()).toEqual(["fault gamma", "auth delta"]);
        click(chip(t.home.fAll));
        await flush();
        expect(rows()).toHaveLength(5);
    });

    it("无匹配出空态文案", async () => {
        renderList();
        const inp = root.querySelector(".task-search") as HTMLInputElement;
        inp.value = "zzz";
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        await flush();
        expect(root.querySelector(".task-empty")?.textContent).toContain(
            t.home.searchEmpty,
        );
    });
});

describe("U8：行内快捷臂", () => {
    it("在途行有 ⏻ 取消钮 → confirm 确认后 api.cancel", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(true);
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("active alpha"),
        )!;
        const btn = row.querySelector(".task-act") as HTMLButtonElement;
        expect(btn.getAttribute("aria-label")).toBe(t.home.cancelTask);
        click(btn);
        await flush();
        expect(mocks.cancel).toHaveBeenCalledWith("a1");
    });

    it("⏻ confirm 拒绝 → 不调 api.cancel", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(false);
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("active alpha"),
        )!;
        click(row.querySelector(".task-act") as HTMLButtonElement);
        await flush();
        expect(mocks.cancel).not.toHaveBeenCalled();
    });

    it("fault 行有 ↻ 重试钮 → 迷你菜单选「重试」→ api.retry + resetLive 重订阅", async () => {
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("fault gamma"),
        )!;
        const btn = row.querySelector(".task-act") as HTMLButtonElement;
        expect(btn.getAttribute("aria-label")).toBe(t.home.retry);
        click(btn);
        await flush();
        const items = [...row.querySelectorAll(".retry-item")];
        const retryAs = (eng: string) =>
            t.home.retryAs.replace("{engine}", eng);
        expect(items.map((x) => x.textContent)).toEqual([
            t.home.retry,
            retryAs(t.home.engineAuto),
            retryAs("tectonic"),
            retryAs("xelatex"),
            retryAs("pdflatex"),
        ]);
        click(items[0] as HTMLElement);
        await flush();
        expect(mocks.retry).toHaveBeenCalledWith("a3");
        expect(mocks.resetLive).toHaveBeenCalledWith("a3");
    });

    it("↻ 菜单引擎子项 → api.retry 带 options.engine（auto 不带 engine 键）", async () => {
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("fault gamma"),
        )!;
        click(row.querySelector(".task-act") as HTMLButtonElement);
        await flush();
        const items = [...row.querySelectorAll(".retry-item")];
        // xelatex → {options:{engine:"xelatex"}}
        click(items[3] as HTMLElement);
        await flush();
        expect(mocks.retry).toHaveBeenCalledWith("a3", {
            options: { engine: "xelatex" },
        });
        // 自动路由 → {options:{}}（不带 engine 键，后端按已存决议）
        mocks.retry.mockClear();
        click(row.querySelector(".task-act") as HTMLButtonElement);
        await flush();
        click(row.querySelectorAll(".retry-item")[1] as HTMLElement);
        await flush();
        expect(mocks.retry).toHaveBeenCalledWith("a3", { options: {} });
    });

    it("needs_auth 行给 ⚙ 设置链接而非 ↻", () => {
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("auth delta"),
        )!;
        const link = row.querySelector("a.task-act") as HTMLAnchorElement;
        expect(link.getAttribute("href")).toBe("#/settings");
        expect(row.querySelector("button.task-act")).toBeNull();
    });

    it("done 行无快捷臂（只有下载/删除）", () => {
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("done beta"),
        )!;
        expect(row.querySelector(".task-act")).toBeNull();
        expect(row.querySelector(".task-dlt")).not.toBeNull();
        expect(row.querySelector(".task-del")).not.toBeNull();
    });
});

describe("U5：清理菜单 + 删除确认框", () => {
    const openMenu = async () => {
        click(root.querySelector(".task-clean") as HTMLElement);
        await flush();
    };

    it("开菜单即 dry-run 预估，菜单项内联可释放量", async () => {
        renderList();
        await openMenu();
        expect(mocks.slimTasks).toHaveBeenCalledWith({ dry: true });
        expect(
            root.querySelector(".maint-slim .menu-hint")?.textContent,
        ).toBe(t.home.maintSlimEst.replace("{size}", "1.4 MB"));
        expect(root.querySelector(".maint-purge .menu-hint")?.textContent).toBe(
            t.home.purgeN.replace("{n}", "4"),
        );
    });

    it("「清理中间文件」实跑 POST /tasks/slim 并回显释放量", async () => {
        renderList();
        await openMenu();
        mocks.slimTasks.mockClear();
        click(root.querySelector(".maint-slim") as HTMLElement);
        await flush();
        expect(mocks.slimTasks).toHaveBeenCalledTimes(1);
        expect(mocks.slimTasks.mock.calls[0]?.[0]?.dry).toBeFalsy();
        expect(mocks.remove).not.toHaveBeenCalled();
        expect(root.querySelector(".task-note")?.textContent).toBe(
            t.home.slimFreed.replace("{size}", "1.4 MB"),
        );
    });

    it("freed_bytes=0 时回显无可清", async () => {
        renderList();
        await openMenu();
        mocks.slimTasks.mockClear();
        mocks.slimTasks.mockResolvedValue({ slimmed: 0, freed_bytes: 0 });
        click(root.querySelector(".maint-slim") as HTMLElement);
        await flush();
        expect(root.querySelector(".task-note")?.textContent).toBe(
            t.home.slimNone,
        );
    });

    it("「删除已结束」出确认框，确认后删全部终态行", async () => {
        renderList();
        await openMenu();
        click(root.querySelector(".maint-purge") as HTMLElement);
        await flush();
        expect(root.querySelector(".purge-box")).not.toBeNull();
        expect(root.querySelector(".maint-menu")).toBeNull();
        click(root.querySelector(".purge-confirm") as HTMLElement);
        await flush();
        // a2/a5 done + a3 fault + a4 needs_auth——终态全口径
        expect(mocks.remove.mock.calls.map((c) => c[0]).sort()).toEqual([
            "a2",
            "a3",
            "a4",
            "a5",
        ]);
        expect(root.querySelector(".purge-box")).toBeNull();
        expect(root.querySelector(".task-note")?.textContent).toBe(
            t.home.purgeDone.replace("{n}", "4"),
        );
    });

    it("确认框取消勾选「已完成」→ 只删未完成", async () => {
        renderList();
        await openMenu();
        click(root.querySelector(".maint-purge") as HTMLElement);
        await flush();
        const cb = root.querySelector(
            ".purge-opt input",
        ) as HTMLInputElement;
        cb.checked = false;
        cb.dispatchEvent(new Event("change", { bubbles: true }));
        await flush();
        expect(
            (root.querySelector(".purge-confirm") as HTMLButtonElement)
                .textContent,
        ).toBe(t.home.purgeDo.replace("{n}", "2"));
        click(root.querySelector(".purge-confirm") as HTMLElement);
        await flush();
        expect(mocks.remove.mock.calls.map((c) => c[0]).sort()).toEqual([
            "a3",
            "a4",
        ]);
    });

    it("确认框取消钮关框不删", async () => {
        renderList();
        await openMenu();
        click(root.querySelector(".maint-purge") as HTMLElement);
        await flush();
        click(root.querySelector(".purge-cancel") as HTMLElement);
        await flush();
        expect(root.querySelector(".purge-box")).toBeNull();
        expect(mocks.remove).not.toHaveBeenCalled();
    });

    it("无终态行时 purge 菜单项 disabled", async () => {
        renderList([snap("b1", { status: "translating", progress: 10 })]);
        await openMenu();
        expect(
            (root.querySelector(".maint-purge") as HTMLButtonElement).disabled,
        ).toBe(true);
    });
});
