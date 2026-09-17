// @vitest-environment jsdom
// Reader 外壳编排回归：
//  - M2：卸载必须 taskStore.unwatch(taskId) 摘 SSE pin
//  - U9：活动任务 document.title 写「N% · 标题」，卸载还原
//  - U10：后台 tab 收到终态 → 标题闪【完成】

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";

const mocks = vi.hoisted(() => ({
    snapshot: vi.fn(),
    reader: vi.fn(),
    files: vi.fn(),
    cancel: vi.fn(),
    openTaskEvents: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            snapshot: mocks.snapshot,
            reader: mocks.reader,
            files: mocks.files,
            cancel: mocks.cancel,
        },
        openTaskEvents: mocks.openTaskEvents,
    };
});

// ReaderView → PdfPane → @pdfslick/core（UMD 顶层要 DOMMatrix，jsdom 没有）；
// 本文件只走进行中/终态面板路径，阅读视图 stub 掉即可
vi.mock("../reader/ReaderView", () => ({ default: () => null }));

import type { TaskEventHandlers, TaskSnapshot } from "../api/client";
import Reader from "../pages/Reader";
import { taskStore } from "../stores/tasks";

const snap = (over: Partial<TaskSnapshot> = {}): TaskSnapshot => ({
    task_id: "t1",
    kind: "arxiv",
    status: "translating",
    progress: 42,
    title: "Paper X",
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    ...over,
});

const handlersOf = (i: number) =>
    mocks.openTaskEvents.mock.calls[i][1] as TaskEventHandlers;

let dispose: (() => void) | undefined;

beforeEach(() => {
    mocks.snapshot.mockReset().mockImplementation(() => Promise.resolve(snap()));
    // done 到达 → loadReader：reader 拉不到（fatal 兜底），manifest 空
    mocks.reader.mockReset().mockRejectedValue(new Error("no reader"));
    mocks.files.mockReset().mockResolvedValue({ artifacts: {} });
    mocks.cancel.mockReset().mockResolvedValue(undefined);
    mocks.openTaskEvents.mockReset().mockImplementation(() => {
        const ch = {
            closed: false,
            close: vi.fn(() => {
                ch.closed = true;
            }),
        };
        return ch;
    });
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("Reader 编排", () => {
    it("进行中 → watch + 进度视图 + 标题带进度；卸载 → unwatch + 标题还原", async () => {
        const unwatch = vi.spyOn(taskStore, "unwatch");
        const prevTitle = document.title;
        dispose = render(
            () => Reader({ taskId: "t1", nav: vi.fn() }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(mocks.openTaskEvents).toHaveBeenCalledWith(
                "t1",
                expect.anything(),
            ),
        );
        expect(document.querySelector(".task-progress")).not.toBeNull();
        await vi.waitFor(() =>
            expect(document.title).toBe("42% · Paper X"),
        );
        dispose();
        dispose = undefined;
        expect(unwatch).toHaveBeenCalledWith("t1");
        expect(document.title).toBe(prevTitle);
    });

    it("后台 tab 收到 done → 标题闪【完成】", async () => {
        dispose = render(
            () => Reader({ taskId: "t1", nav: vi.fn() }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(mocks.openTaskEvents).toHaveBeenCalled(),
        );
        // 真实服务器建连即推 snapshot 帧（upsertTask 填充行——done 只补丁在册行）
        handlersOf(0).snapshot?.(snap());
        // 模拟用户切走：hidden 之后 done 到达才闪
        Object.defineProperty(document, "hidden", {
            configurable: true,
            get: () => true,
        });
        vi.useFakeTimers();
        handlersOf(0).done?.({ status: "done", artifacts: {}, stats: {} });
        await vi.advanceTimersByTimeAsync(1200);
        expect(document.title).toContain("【");
        vi.useRealTimers();
    });
});
