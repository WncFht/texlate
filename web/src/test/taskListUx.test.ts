// @vitest-environment jsdom
// TaskList 交互约束：
//  - 行内产物下载改交互触发（悬停/聚焦预取 + 折叠钮展开），挂载不再每行
//    发 api.files 突发；点开折叠才可能有请求。
//  - 一单删除在飞时其它行删除钮 disabled（防静默无响应）。

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

import type { TaskSnapshot } from "../api/client";
import { snap as fakeSnap } from "./fakes";
import { flush } from "./_taskkit";
import { renderList } from "./_taskdom";

let dispose: (() => void) | undefined;

// 下载行语义是 doc 任务——kind 经 fakes.snap 的 over 覆写，其余缺省同源
const snap = (id: string, over: Partial<TaskSnapshot> = {}): TaskSnapshot =>
    fakeSnap(id, { kind: "docx", ...over });

beforeEach(() => {
    mocks.files.mockReset().mockResolvedValue({
        artifacts: {
            zh_docx: {
                bytes: 1,
                sha256: "x",
                created_at: 0,
                url: "/f/zh.docx",
            },
        },
    });
    mocks.deleteTask.mockReset();
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("行内产物下载 —— 懒拉时机", () => {
    it("挂载不拉 manifest（无 artifacts 行零请求）", async () => {
        dispose = renderList([snap("t_d1"), snap("t_d2")]);
        await flush();
        expect(mocks.files).not.toHaveBeenCalled();
    });

    it("点开折叠钮 → 恰好一次 api.files，产物链出现", async () => {
        dispose = renderList([snap("t_d1")]);
        const toggle =
            document.body.querySelector<HTMLButtonElement>(".task-dlt");
        expect(toggle).toBeTruthy();
        toggle!.click();
        await flush();

        expect(mocks.files).toHaveBeenCalledTimes(1);
        expect(mocks.files).toHaveBeenCalledWith("t_d1");
        expect(document.body.querySelectorAll(".task-dl").length).toBe(1);
    });

    it("悬停预取后再点开 —— 仍只发一次", async () => {
        dispose = renderList([snap("t_d1")]);
        const toggle = document.body.querySelector<HTMLElement>(".task-dlt")!;
        toggle.dispatchEvent(new Event("pointerenter", { bubbles: true }));
        await flush();
        expect(mocks.files).toHaveBeenCalledTimes(1);

        document.body.querySelector<HTMLButtonElement>(".task-dlt")!.click();
        await flush();
        expect(mocks.files).toHaveBeenCalledTimes(1);
        expect(document.body.querySelectorAll(".task-dl").length).toBe(1);
    });

    it("snapshot.artifacts 已在 → 不拉 manifest 也能展开直链", async () => {
        dispose = renderList([
            snap("t_d1", {
                artifacts: { zh_docx: "/api/files/t_d1/zh.docx" },
            }),
        ]);
        document.body.querySelector<HTMLButtonElement>(".task-dlt")!.click();
        await flush();
        expect(mocks.files).not.toHaveBeenCalled();
        const a = document.body.querySelector<HTMLAnchorElement>(".task-dl");
        expect(a?.href).toContain("zh.docx");
    });
});

describe("删除互斥", () => {
    it("一单在飞 → 其余行删除钮 disabled", async () => {
        mocks.deleteTask.mockImplementation(() => new Promise(() => {}));
        dispose = renderList([
            snap("t_a", { kind: "arxiv" }),
            snap("t_b", { kind: "arxiv" }),
        ]);
        const dels =
            document.body.querySelectorAll<HTMLButtonElement>(".task-del");
        expect(dels.length).toBe(2);

        // 两击确认：第一击进 armed 态（文字变「确认删除？」），第二击才执行
        dels[0].click();
        await flush();
        const armed =
            document.body.querySelectorAll<HTMLButtonElement>(".task-del");
        expect(armed[0].classList.contains("armed")).toBe(true);
        expect(mocks.deleteTask).not.toHaveBeenCalled();

        armed[0].click();
        await flush();
        const after =
            document.body.querySelectorAll<HTMLButtonElement>(".task-del");
        expect(after[0].disabled).toBe(true);
        expect(after[1].disabled).toBe(true);
    });
});
