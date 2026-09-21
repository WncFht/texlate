// @vitest-environment jsdom
// Home 批量上传（home/upload.ts uploadBatch 多文件分支）：顺序提交不并发、
// 单件失败不阻断后续、错误「；」汇总、批路不抢路由（无 nav）、结案一次
// onBatchDone（tasks refresh）；busy 闸与单件路同例。此前零覆盖。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
    translate: vi.fn(),
    upload: vi.fn(),
    shareImport: vi.fn(),
}));

// vi.mock 提升限制——工厂体内再引 _homekit（顶层 import 进不了 hoisted 作用域）
vi.mock("../api/client", async (importOriginal) =>
    (await import("./_homekit")).buildApiModule(
        await importOriginal<typeof import("../api/client")>(),
        mocks,
    ),
);

import { ApiError } from "../api/client";
import Home from "../pages/Home";
import {
    flush,
    mountHome,
    pick,
    resetHomeMocks,
    RESP,
    type,
} from "./_homekit";

const errText = () =>
    document.body.querySelector(".form-error")?.textContent ?? "";

beforeEach(() => resetHomeMocks(mocks));

describe("Home 批量上传 —— 多文件分支", () => {
    it("顺序提交不并发：第二件等第一件结案才发出", async () => {
        let resolveFirst: ((v: typeof RESP) => void) | undefined;
        mocks.upload
            .mockImplementationOnce(
                () => new Promise<typeof RESP>((r) => (resolveFirst = r)),
            )
            .mockResolvedValue(RESP);
        const { file } = mountHome(Home);
        pick(file, [
            new File(["a"], "a.tex"),
            new File(["b"], "b.tex"),
        ]);

        await vi.waitFor(() =>
            expect(mocks.upload).toHaveBeenCalledTimes(1),
        );
        expect(mocks.upload.mock.calls[0][0].name).toBe("a.tex");
        await flush();
        // 第一件未结案 → 第二件不得发出（顺序语义）
        expect(mocks.upload).toHaveBeenCalledTimes(1);

        resolveFirst!(RESP);
        await vi.waitFor(() =>
            expect(mocks.upload).toHaveBeenCalledTimes(2),
        );
        expect(mocks.upload.mock.calls[1][0].name).toBe("b.tex");
    });

    it("单件失败不阻断后续：错误「；」汇总且批路不抢路由", async () => {
        mocks.upload
            .mockRejectedValueOnce(new ApiError(500, "boom-a"))
            .mockRejectedValueOnce(new ApiError(400, "boom-b"))
            .mockResolvedValue(RESP);
        const { nav, file } = mountHome(Home);
        pick(file, [
            new File(["a"], "a.tex"),
            new File(["b"], "b.tex"),
            new File(["c"], "c.tex"),
        ]);

        await vi.waitFor(() =>
            expect(mocks.upload).toHaveBeenCalledTimes(3),
        );
        await flush();
        await flush();

        // 失败文件名 + 文案聚合；批量不跳阅读器
        expect(errText()).toContain("a.tex");
        expect(errText()).toContain("boom-a");
        expect(errText()).toContain("b.tex");
        expect(errText()).toContain("boom-b");
        expect(errText()).toContain("；");
        expect(nav).not.toHaveBeenCalled();
    });

    it("全批结案后 onBatchDone 恰好一次（tasks refresh）", async () => {
        mocks.upload.mockResolvedValue(RESP);
        const { file } = mountHome(Home);
        await flush();
        mocks.tasks.mockClear(); // 撇开挂载时 ensureFresh 的那一拍

        pick(file, [
            new File(["a"], "a.tex"),
            new File(["b"], "b.tex"),
        ]);
        await vi.waitFor(() =>
            expect(mocks.upload).toHaveBeenCalledTimes(2),
        );
        await flush();
        await flush();

        expect(mocks.tasks).toHaveBeenCalledTimes(1);
    });

    it("busy 闸：translate 在飞时批量上传不发请求", async () => {
        mocks.translate.mockImplementation(() => new Promise(() => {}));
        const { input, form, file } = mountHome(Home);
        type(input, "2501.14787");
        form.dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
        );
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());

        pick(file, [
            new File(["a"], "a.tex"),
            new File(["b"], "b.tex"),
        ]);
        await flush();
        await flush();
        expect(mocks.upload).not.toHaveBeenCalled();
    });
});
