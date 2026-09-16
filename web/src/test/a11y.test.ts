// @vitest-environment jsdom
// a11y 散点回归：DocInfo 弹层 Escape 关闭；TaskList 行进度条
// role=progressbar 带任务名 aria-label。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    files: vi.fn(),
    deleteTask: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            files: mocks.files,
            deleteTask: mocks.deleteTask,
        },
    };
});

import { render } from "solid-js/web";
import DocInfo from "../reader/DocInfo";
import TaskList from "../components/TaskList";
import type { TaskSnapshot } from "../api/client";

const flush = () => new Promise((r) => setTimeout(r, 0));
let dispose: (() => void) | undefined;

beforeEach(() => {
    mocks.files.mockReset().mockResolvedValue({ artifacts: {} });
    mocks.deleteTask.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("DocInfo 文档信息弹层", () => {
    const store = { numPages: 5, filename: "a.pdf" } as never;

    it("Escape → onClose", async () => {
        const onClose = vi.fn();
        dispose = render(
            () => DocInfo({ store, onClose }),
            document.body,
        );
        await flush();
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("非 Escape 键不触发关闭", async () => {
        const onClose = vi.fn();
        dispose = render(
            () => DocInfo({ store, onClose }),
            document.body,
        );
        await flush();
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
        expect(onClose).not.toHaveBeenCalled();
    });
});

describe("TaskList 进度条 a11y", () => {
    it(".task-bar 有 role=progressbar + 任务名 aria-label", () => {
        const task: TaskSnapshot = {
            task_id: "t_aa",
            kind: "arxiv",
            status: "done",
            progress: 100,
            title: "My Paper",
            created_at: 1_700_000_000,
            updated_at: 1_700_000_000,
        };
        dispose = render(
            () => TaskList({ tasks: [task], onOpen: vi.fn() }),
            document.body,
        );
        const bar = document.body.querySelector(".task-bar");
        expect(bar?.getAttribute("role")).toBe("progressbar");
        expect(bar?.getAttribute("aria-label")).toBe("My Paper");
        expect(bar?.getAttribute("aria-valuenow")).toBe("100");
    });
});
