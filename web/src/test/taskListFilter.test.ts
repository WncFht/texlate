// @vitest-environment jsdom
// TaskList U5/U8：搜索 + 筛选 chips + 活动置顶分组 + 批量清理已完成；
// 行内 ⏻ 取消（在途）/ ↻ 重试（可重试终态）/ ⚙ 设置链（needs_auth）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    cancel: vi.fn(),
    retry: vi.fn(),
    files: vi.fn(),
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

import { render } from "solid-js/web";
import TaskList from "../components/TaskList";
import type { TaskSnapshot } from "../api/client";

const flush = () => new Promise((r) => setTimeout(r, 0));
let dispose: (() => void) | undefined;
let root: HTMLDivElement;

const snap = (id: string, over: Partial<TaskSnapshot> = {}): TaskSnapshot => ({
    task_id: id,
    kind: "arxiv",
    status: "done",
    progress: 100,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    ...over,
});

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
    mocks.remove.mockReset().mockResolvedValue(undefined);
    mocks.resetLive.mockReset();
    mocks.refresh.mockReset();
    vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    root.remove();
    vi.restoreAllMocks();
});

const renderList = (tasks = seed) => {
    dispose = render(() => TaskList({ tasks, onOpen: () => {} }), root);
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
    });

    it("筛选 chips：进行中/已完成/异常", async () => {
        renderList();
        const chip = (label: string) =>
            [...root.querySelectorAll(".task-chip")].find(
                (b) => b.textContent === label,
            )!;
        click(chip("进行中"));
        await flush();
        expect(titles()).toEqual(["active alpha"]);
        click(chip("已完成"));
        await flush();
        expect(titles()).toEqual(["done epsilon", "done beta"]);
        click(chip("异常"));
        await flush();
        expect(titles()).toEqual(["fault gamma", "auth delta"]);
        click(chip("全部"));
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
            "没有匹配",
        );
    });
});

describe("U8：行内快捷臂", () => {
    it("在途行有 ⏻ 取消钮 → api.cancel", async () => {
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("active alpha"),
        )!;
        const btn = row.querySelector(".task-act") as HTMLButtonElement;
        expect(btn.getAttribute("aria-label")).toBe("取消任务");
        click(btn);
        await flush();
        expect(mocks.cancel).toHaveBeenCalledWith("a1");
    });

    it("fault 行有 ↻ 重试钮 → api.retry + resetLive 重订阅", async () => {
        renderList();
        const row = [...root.querySelectorAll(".task-wrap")].find((w) =>
            w.textContent?.includes("fault gamma"),
        )!;
        const btn = row.querySelector(".task-act") as HTMLButtonElement;
        expect(btn.getAttribute("aria-label")).toBe("重试");
        click(btn);
        await flush();
        expect(mocks.retry).toHaveBeenCalledWith("a3");
        expect(mocks.resetLive).toHaveBeenCalledWith("a3");
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

describe("U5：批量清理已完成", () => {
    it("清理钮只删 done 行", async () => {
        renderList();
        const btn = root.querySelector(".task-clean") as HTMLButtonElement;
        expect(btn.disabled).toBe(false);
        click(btn);
        await flush();
        expect(mocks.remove.mock.calls.map((c) => c[0]).sort()).toEqual([
            "a2",
            "a5",
        ]);
    });

    it("无 done 行时清理钮 disabled", () => {
        renderList([snap("b1", { status: "translating", progress: 10 })]);
        expect(
            (root.querySelector(".task-clean") as HTMLButtonElement).disabled,
        ).toBe(true);
    });
});
